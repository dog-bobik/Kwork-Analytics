from __future__ import annotations
import secrets
from typing import Any
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from backend.api.dependencies import current_user
from backend.api.schemas import LoginRequest
from backend.core.config import settings
from backend.core.security import token_hash
from backend.db import repositories
from backend.db.models import User
from backend.kwork_client import KworkError
from backend.services import analytics
from backend.services.authentication import authenticate
from backend.services.synchronization import sync_meta

router = APIRouter(prefix="/api")

@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "database": True, "framework": "FastAPI", "orm": "SQLAlchemy"}

@router.get("/auth/status")
async def auth_status(kwork_pulse_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    if not kwork_pulse_session:
        return {"authenticated": False}
    user = await repositories.get_user_by_session(token_hash(kwork_pulse_session))
    return {"authenticated": user is not None, "user": user.profile if user else None}

@router.post("/auth/login")
async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    login_value, password = body.login.strip(), body.password
    if not login_value or not password:
        raise HTTPException(status_code=422, detail="Логин и пароль обязательны")
    try:
        result = await authenticate(login_value, password, (body.phone_last or "").strip() or None)
    except (KworkError, ValueError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    raw_session = secrets.token_urlsafe(48)
    await repositories.create_web_session(result.user.id, token_hash(raw_session))
    response.set_cookie(settings.session_cookie, raw_session, httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=settings.session_days * 86400)
    return {"authenticated": True, "user": result.user.profile, "connected_to_kwork": result.connected_to_kwork}

@router.post("/auth/logout")
async def logout(response: Response, kwork_pulse_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    if kwork_pulse_session:
        await repositories.delete_web_session(token_hash(kwork_pulse_session))
    response.delete_cookie(settings.session_cookie)
    return {"authenticated": False}

@router.get("/offers")
async def offers(user: User = Depends(current_user)) -> dict[str, Any]:
    items = await repositories.current_items(user.id, "offers")
    return {"offers": items, "summary": analytics.summarize_offers(items), "today": await analytics.offer_analytics_today(user.id), "meta": sync_meta(user)}

@router.get("/kworks")
async def kworks(user: User = Depends(current_user)) -> dict[str, Any]:
    items = await repositories.current_items(user.id, "kworks")
    today = await analytics.kwork_analytics_today(user.id)
    for item in items:
        item_today = today["items"].get(repositories.external_id(item, "kworks"), {})
        item["today"] = item_today
        item["views_today"] = item_today.get("views", 0)
    today.pop("items", None)
    return {"kworks": items, "today": today, "meta": sync_meta(user)}

@router.get("/analytics/{resource}/{item_id}/today")
async def item_analytics(resource: str, item_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    if resource not in {"offers", "kworks"}:
        raise HTTPException(status_code=404, detail="Аналитика для этого раздела недоступна")
    result = await analytics.item_analytics_today(user.id, resource, item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Сегодня ещё нет снимков для этого объекта")
    return {"analytics": result, "meta": sync_meta(user)}

@router.get("/profile/me")
async def my_profile(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"profile": user.profile, "kworks": await repositories.current_items(user.id, "kworks"), "reviews": await repositories.current_items(user.id, "reviews"), "meta": sync_meta(user)}
