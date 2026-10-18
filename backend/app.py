from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel

from backend import database
from backend.database import User
from backend.kwork_client import KworkClient, KworkError

SESSION_COOKIE = "kwork_pulse_session"
SYNC_INTERVAL_SECONDS = max(int(os.getenv("SYNC_INTERVAL_SECONDS", "900")), 60)
ACTIVE_SYNCS: dict[int, asyncio.Task[None]] = {}


def _fernet() -> Fernet:
    secret = os.getenv("APP_SECRET", "kwork-pulse-local-server-secret")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise KworkError("Не удалось расшифровать сохранённый токен Kwork") from error


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def summarize(offers: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(offers),
        "read": sum(item.get("is_read") is True for item in offers),
        "unread": sum(item.get("is_read") is not True for item in offers),
        "active": sum(item.get("is_actual") is True for item in offers),
        "viewedByMe": sum(isinstance(item.get("project"), dict) and item["project"].get("is_viewed") is True for item in offers),
        "withOrders": sum((item.get("market") or {}).get("buyer_order_count", 0) > 0 for item in offers),
        "buyerOrders": sum((item.get("market") or {}).get("buyer_order_count", 0) for item in offers),
    }


async def enrich_offers(client: KworkClient, offers: list[dict[str, Any]]) -> None:
    semaphore = asyncio.Semaphore(6)

    async def enrich(offer: dict[str, Any]) -> None:
        project = offer.get("project")
        project_id = offer.get("want_id") or (project.get("id") if isinstance(project, dict) else None)
        if not isinstance(project_id, int) or project_id <= 0:
            offer["market"] = {"buyer_order_count": 0, "available": False}
            return
        try:
            async with semaphore:
                offer["market"] = {**await client.get_project_market_data(project_id), "available": True}
        except KworkError:
            offer["market"] = {"buyer_order_count": 0, "available": False}

    await asyncio.gather(*(enrich(offer) for offer in offers))
    project_ids = [item.get("want_id") for item in offers if isinstance(item.get("want_id"), int)]
    try:
        selected = await client.get_selected_orders(project_ids)
    except KworkError:
        selected = {}
    for offer in offers:
        if offer.get("want_id") in selected:
            offer.setdefault("market", {}).update(selected[offer["want_id"]])


async def sync_user(user_id: int) -> None:
    user = await database.get_user(user_id)
    if user is None:
        return
    try:
        async with KworkClient(token=decrypt_token(user.token_encrypted), timeout_seconds=45) as client:
            actor = await client.get_actor()
            offers, kworks, portfolio = await asyncio.gather(
                client.get_all_offers(),
                client.get_all_kworks(),
                client.get_all_portfolio(),
            )
            await enrich_offers(client, offers)
            username = str(actor.get("username") or user.username or "")
            public_profile, reviews = await asyncio.gather(
                client.get_user_by_username(username),
                client.get_all_user_reviews(int(actor.get("id") or actor.get("USERID") or actor.get("user_id"))),
            )
            profile_bundle = {
                "profile": public_profile,
                "kworks": kworks,
                "portfolio": portfolio,
                "reviews": reviews,
            }
        await database.save_sync(user_id, offers, kworks, portfolio, actor)
        await database.save_profile(user_id, username, profile_bundle)
    except (KworkError, ValueError, OSError) as error:
        await database.record_sync_error(user_id, str(error))


def schedule_sync(user_id: int) -> bool:
    current = ACTIVE_SYNCS.get(user_id)
    if current and not current.done():
        return False

    async def runner() -> None:
        try:
            await sync_user(user_id)
        finally:
            ACTIVE_SYNCS.pop(user_id, None)

    ACTIVE_SYNCS[user_id] = asyncio.create_task(runner(), name=f"kwork-sync-{user_id}")
    return True


def is_stale(user: User) -> bool:
    if user.last_sync_at is None:
        return True
    moment = user.last_sync_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc)-moment).total_seconds() >= SYNC_INTERVAL_SECONDS


async def scheduler_loop() -> None:
    while True:
        try:
            for user_id in await database.users_due(SYNC_INTERVAL_SECONDS):
                schedule_sync(user_id)
        except Exception:
            # Следующий цикл восстановит работу после временной ошибки БД.
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await database.init_database()
    scheduler = asyncio.create_task(scheduler_loop(), name="kwork-scheduler")
    yield
    scheduler.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler
    for task in list(ACTIVE_SYNCS.values()):
        task.cancel()
    if ACTIVE_SYNCS:
        await asyncio.gather(*list(ACTIVE_SYNCS.values()), return_exceptions=True)
    await database.close_database()


app = FastAPI(title="Kwork Pulse API", version="3.0", lifespan=lifespan)


class LoginRequest(BaseModel):
    login: str
    password: str
    phone_last: str | None = None


async def current_user(kwork_pulse_session: str | None = Cookie(default=None)) -> User:
    if not kwork_pulse_session:
        raise HTTPException(status_code=401, detail="Требуется вход в Kwork")
    user = await database.get_user_by_session(token_hash(kwork_pulse_session))
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user


def sync_meta(user: User) -> dict[str, Any]:
    stale = is_stale(user)
    if stale:
        schedule_sync(user.id)
    return {
        "stale": stale,
        "syncing": user.id in ACTIVE_SYNCS,
        "last_sync_at": user.last_sync_at.isoformat() if user.last_sync_at else None,
        "sync_error": user.sync_error,
        "interval_seconds": SYNC_INTERVAL_SECONDS,
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "database": True, "framework": "FastAPI", "orm": "SQLAlchemy"}


@app.get("/api/auth/status")
async def auth_status(kwork_pulse_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    if not kwork_pulse_session:
        return {"authenticated": False}
    user = await database.get_user_by_session(token_hash(kwork_pulse_session))
    return {"authenticated": user is not None, "user": user.profile if user else None}


@app.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    login_value, password = body.login.strip(), body.password
    if not login_value or not password:
        raise HTTPException(status_code=422, detail="Логин и пароль обязательны")
    try:
        async with KworkClient(login_value, password, phone_last=(body.phone_last or "").strip() or None) as client:
            actor = await client.get_actor()
            token = client.token
        if not token:
            raise KworkError("Kwork не вернул токен")
    except (KworkError, ValueError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    user = await database.upsert_user(login_value, encrypt_token(token), actor)
    raw_session = secrets.token_urlsafe(48)
    await database.create_web_session(user.id, token_hash(raw_session))
    response.set_cookie(SESSION_COOKIE, raw_session, httponly=True, samesite="strict", max_age=2592000)
    schedule_sync(user.id)
    return {"authenticated": True, "user": actor, "syncing": True}


@app.post("/api/auth/logout")
async def logout(response: Response, kwork_pulse_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    if kwork_pulse_session:
        await database.delete_web_session(token_hash(kwork_pulse_session))
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@app.get("/api/offers")
async def offers(user: User = Depends(current_user)) -> dict[str, Any]:
    items = await database.current_items(user.id, "offers")
    return {"offers": items, "summary": summarize(items), "meta": sync_meta(user)}


@app.get("/api/kworks")
async def kworks(user: User = Depends(current_user)) -> dict[str, Any]:
    items = await database.current_items(user.id, "kworks")
    deltas = await database.view_deltas_today(user.id, "kworks")
    for item in items:
        item["views_today"] = deltas.get(database.external_id(item, "kworks"), 0)
    return {"kworks": items, "meta": sync_meta(user)}


@app.get("/api/portfolio")
async def portfolio(user: User = Depends(current_user)) -> dict[str, Any]:
    items = await database.current_items(user.id, "portfolio")
    deltas = await database.view_deltas_today(user.id, "portfolio")
    for item in items:
        item["views_today"] = deltas.get(database.external_id(item, "portfolio"), 0)
    return {"portfolio": items, "meta": sync_meta(user)}


async def profile_response(user: User, username: str) -> dict[str, Any]:
    clean_username = username.strip()
    if not clean_username or len(clean_username) > 64:
        raise HTTPException(status_code=422, detail="Некорректное имя пользователя")
    try:
        async with KworkClient(token=decrypt_token(user.token_encrypted), timeout_seconds=45) as client:
            bundle = await client.get_profile_bundle(clean_username)
        await database.save_profile(user.id, clean_username, bundle)
        return {**bundle, "cached": False, "meta": sync_meta(user)}
    except (KworkError, ValueError, OSError) as error:
        cached = await database.cached_profile(user.id, clean_username)
        if cached is not None:
            return {**cached, "cached": True, "profile_error": str(error), "meta": sync_meta(user)}
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/profiles/me")
async def my_profile(user: User = Depends(current_user)) -> dict[str, Any]:
    username = str(user.profile.get("username") or user.username or "")
    return await profile_response(user, username)


@app.get("/api/profiles/{username}")
async def public_profile(username: str, user: User = Depends(current_user)) -> dict[str, Any]:
    return await profile_response(user, username)
