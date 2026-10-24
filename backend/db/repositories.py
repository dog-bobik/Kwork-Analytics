from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select

from backend.core.config import settings
from backend.db.models import AnalyticsSnapshot, CurrentItem, SyncRun, User, WebSession
from backend.db.session import SessionFactory


def external_id(item: dict[str, Any], resource: str) -> str:
    return str(item.get("id") or item.get("want_id") or item.get("PID") or f"{resource}-unknown")


async def find_user_by_login(login: str) -> User | None:
    async with SessionFactory() as db:
        return await db.scalar(select(User).where(func.lower(User.login) == login.lower()))


async def upsert_user(
    login: str,
    encrypted_token: str,
    password_hash: str,
    actor: dict[str, Any],
) -> User:
    kwork_id = str(actor.get("id") or actor.get("USERID") or actor.get("user_id") or login)
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.kwork_user_id == kwork_id))
        if user is None:
            user = User(
                kwork_user_id=kwork_id,
                username=actor.get("username"),
                login=login,
                password_hash=password_hash,
                token_encrypted=encrypted_token,
                profile=actor,
            )
            db.add(user)
        else:
            user.login = login
            user.password_hash = password_hash
            user.token_encrypted = encrypted_token
            user.profile = actor
            user.username = actor.get("username") or user.username
            user.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
        return user


async def create_web_session(user_id: int, hashed_token: str) -> None:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as db:
        await db.execute(delete(WebSession).where(WebSession.expires_at < now))
        db.add(
            WebSession(
                token_hash=hashed_token,
                user_id=user_id,
                expires_at=now + timedelta(days=settings.session_days),
            )
        )
        await db.commit()


async def get_user_by_session(hashed_token: str) -> User | None:
    async with SessionFactory() as db:
        return await db.scalar(
            select(User)
            .join(WebSession, WebSession.user_id == User.id)
            .where(
                WebSession.token_hash == hashed_token,
                WebSession.expires_at > datetime.now(timezone.utc),
            )
        )


async def delete_web_session(hashed_token: str) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(WebSession).where(WebSession.token_hash == hashed_token))
        await db.commit()


async def users_due(interval_seconds: int) -> list[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=interval_seconds)
    async with SessionFactory() as db:
        result = await db.scalars(
            select(User.id).where((User.last_sync_at.is_(None)) | (User.last_sync_at < cutoff))
        )
        return list(result.all())


async def get_user(user_id: int) -> User | None:
    async with SessionFactory() as db:
        return await db.get(User, user_id)


async def save_sync(
    user_id: int,
    offers: list[dict[str, Any]],
    kworks: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    actor: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    resources = (("offers", offers), ("kworks", kworks), ("reviews", reviews))
    async with SessionFactory() as db, db.begin():
        for resource, items in resources:
            await db.execute(
                delete(CurrentItem).where(
                    CurrentItem.user_id == user_id, CurrentItem.resource == resource
                )
            )
            for item in items:
                item_id = external_id(item, resource)
                db.add(
                    CurrentItem(
                        user_id=user_id,
                        resource=resource,
                        external_id=item_id,
                        payload=item,
                        updated_at=now,
                    )
                )
                if resource in {"offers", "kworks"}:
                    db.add(
                        AnalyticsSnapshot(
                            user_id=user_id,
                            resource=resource,
                            external_id=item_id,
                            payload=item,
                            captured_at=now,
                        )
                    )
            db.add(
                SyncRun(
                    user_id=user_id,
                    resource=resource,
                    item_count=len(items),
                    status="success",
                    created_at=now,
                )
            )
        user = await db.get(User, user_id)
        if user:
            user.profile = actor
            user.username = actor.get("username") or user.username
            user.last_sync_at = now
            user.sync_error = None


async def record_sync_error(user_id: int, message: str) -> None:
    async with SessionFactory() as db, db.begin():
        user = await db.get(User, user_id)
        if user:
            user.sync_error = message[:1000]
            user.last_sync_at = datetime.now(timezone.utc)
        db.add(SyncRun(user_id=user_id, resource="all", item_count=0, status="error", error=message[:1000]))


async def current_items(user_id: int, resource: str) -> list[dict[str, Any]]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(CurrentItem)
                .where(CurrentItem.user_id == user_id, CurrentItem.resource == resource)
                .order_by(CurrentItem.id)
            )
        ).all()
        return [dict(row.payload) for row in rows]
