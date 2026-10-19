from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, delete, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "app_users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kwork_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    login: Mapped[str] = mapped_column(String(255))
    token_encrypted: Mapped[str] = mapped_column(Text)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class WebSession(Base):
    __tablename__ = "web_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CurrentItem(Base):
    __tablename__ = "current_items"
    __table_args__ = (UniqueConstraint("user_id", "resource", "external_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    resource: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource: Mapped[str] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://kwork:kwork@127.0.0.1:5432/kwork_analytics")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # Безопасная миграция старой локальной схемы aiohttp/asyncpg.
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS status VARCHAR(32)"))
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS error TEXT"))
        await connection.execute(text("ALTER TABLE analytics_snapshots ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS sync_runs_user_id_idx ON sync_runs(user_id)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS analytics_snapshots_user_id_idx ON analytics_snapshots(user_id)"))


async def close_database() -> None:
    await engine.dispose()


def session() -> AsyncSession:
    return SessionFactory()


def external_id(item: dict[str, Any], resource: str) -> str:
    return str(item.get("id") or item.get("want_id") or item.get("PID") or f"{resource}-unknown")


async def upsert_user(login: str, encrypted_token: str, actor: dict[str, Any]) -> User:
    kwork_id = str(actor.get("id") or actor.get("USERID") or actor.get("user_id") or login)
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.kwork_user_id == kwork_id))
        if user is None:
            user = User(kwork_user_id=kwork_id, username=actor.get("username"), login=login, token_encrypted=encrypted_token, profile=actor)
            db.add(user)
        else:
            user.login, user.token_encrypted, user.profile = login, encrypted_token, actor
            user.username = actor.get("username") or user.username
            user.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
        return user


async def create_web_session(user_id: int, token_hash: str) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(WebSession).where(WebSession.expires_at < datetime.now(timezone.utc)))
        db.add(WebSession(token_hash=token_hash, user_id=user_id, expires_at=datetime.now(timezone.utc)+timedelta(days=30)))
        await db.commit()


async def get_user_by_session(token_hash: str) -> User | None:
    async with SessionFactory() as db:
        return await db.scalar(select(User).join(WebSession, WebSession.user_id == User.id).where(WebSession.token_hash == token_hash, WebSession.expires_at > datetime.now(timezone.utc)))


async def delete_web_session(token_hash: str) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(WebSession).where(WebSession.token_hash == token_hash))
        await db.commit()


async def users_due(interval_seconds: int) -> list[int]:
    cutoff = datetime.now(timezone.utc)-timedelta(seconds=interval_seconds)
    async with SessionFactory() as db:
        return list((await db.scalars(select(User.id).where((User.last_sync_at.is_(None)) | (User.last_sync_at < cutoff)))).all())


async def get_user(user_id: int) -> User | None:
    async with SessionFactory() as db:
        return await db.get(User, user_id)


async def save_sync(
    user_id: int,
    offers: list[dict[str, Any]],
    kworks: list[dict[str, Any]],
    portfolio: list[dict[str, Any]],
    actor: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as db, db.begin():
        for resource, items in (("offers", offers), ("kworks", kworks), ("portfolio", portfolio)):
            await db.execute(delete(CurrentItem).where(CurrentItem.user_id == user_id, CurrentItem.resource == resource))
            for item in items:
                item_id = external_id(item, resource)
                db.add(CurrentItem(user_id=user_id, resource=resource, external_id=item_id, payload=item, updated_at=now))
                db.add(AnalyticsSnapshot(user_id=user_id, resource=resource, external_id=item_id, payload=item, captured_at=now))
            db.add(SyncRun(user_id=user_id, resource=resource, item_count=len(items), status="success", created_at=now))
        user = await db.get(User, user_id)
        if user:
            user.profile, user.username, user.last_sync_at, user.sync_error = actor, actor.get("username") or user.username, now, None


async def record_sync_error(user_id: int, message: str) -> None:
    async with SessionFactory() as db, db.begin():
        user = await db.get(User, user_id)
        if user:
            user.sync_error = message[:1000]
            user.last_sync_at = datetime.now(timezone.utc)
        db.add(SyncRun(user_id=user_id, resource="all", item_count=0, status="error", error=message[:1000]))


async def current_items(user_id: int, resource: str) -> list[dict[str, Any]]:
    async with SessionFactory() as db:
        rows = (await db.scalars(select(CurrentItem).where(CurrentItem.user_id == user_id, CurrentItem.resource == resource).order_by(CurrentItem.id))).all()
        return [dict(row.payload) for row in rows]


async def save_profile(user_id: int, username: str, payload: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    profile_id = username.strip().lower()
    async with SessionFactory() as db, db.begin():
        await db.execute(
            delete(CurrentItem).where(
                CurrentItem.user_id == user_id,
                CurrentItem.resource == "profiles",
                CurrentItem.external_id == profile_id,
            )
        )
        db.add(CurrentItem(user_id=user_id, resource="profiles", external_id=profile_id, payload=payload, updated_at=now))
        db.add(AnalyticsSnapshot(user_id=user_id, resource="profiles", external_id=profile_id, payload=payload, captured_at=now))


async def cached_profile(user_id: int, username: str) -> dict[str, Any] | None:
    profile_id = username.strip().lower()
    async with SessionFactory() as db:
        row = await db.scalar(
            select(CurrentItem).where(
                CurrentItem.user_id == user_id,
                CurrentItem.resource == "profiles",
                CurrentItem.external_id == profile_id,
            )
        )
        return dict(row.payload) if row else None


def snapshot_views(payload: dict[str, Any], resource: str) -> int:
    if resource == "portfolio":
        return int(payload.get("views_dirty") or payload.get("views") or 0)
    activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else {}
    return int(activity.get("views") or payload.get("views_dirty") or payload.get("views") or 0)


def snapshot_number(payload: dict[str, Any], *keys: str) -> int:
    activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else {}
    for source in (activity, payload):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    continue
    return 0


def happened_today(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit():
            raw = float(value)
            moment = datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, tz=timezone.utc)
        else:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return False
    local_zone = ZoneInfo("Asia/Yekaterinburg")
    return moment.astimezone(local_zone).date() == datetime.now(local_zone).date()


async def snapshots_today(user_id: int, resource: str) -> tuple[dict[str, list[dict[str, Any]]], datetime | None, int]:
    local_now = datetime.now(ZoneInfo("Asia/Yekaterinburg"))
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionFactory() as db:
        rows = (await db.scalars(select(AnalyticsSnapshot).where(
            AnalyticsSnapshot.user_id == user_id,
            AnalyticsSnapshot.resource == resource,
            AnalyticsSnapshot.captured_at >= start,
        ).order_by(AnalyticsSnapshot.captured_at))).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.external_id, []).append(dict(row.payload))
    return grouped, rows[0].captured_at if rows else None, len(rows)


async def kwork_analytics_today(user_id: int) -> dict[str, Any]:
    grouped, measured_from, samples = await snapshots_today(user_id, "kworks")
    items: dict[str, dict[str, int]] = {}
    for item_id, payloads in grouped.items():
        first_payload, last_payload = payloads[0], payloads[-1]
        items[item_id] = {
            "views": max(snapshot_views(last_payload, "kworks") - snapshot_views(first_payload, "kworks"), 0),
            "sales": max(snapshot_number(last_payload, "orders", "sales", "orders_count") - snapshot_number(first_payload, "orders", "sales", "orders_count"), 0),
            "earned": max(snapshot_number(last_payload, "earned", "revenue") - snapshot_number(first_payload, "earned", "revenue"), 0),
        }
    return {
        "views": sum(item["views"] for item in items.values()),
        "sales": sum(item["sales"] for item in items.values()),
        "earned": sum(item["earned"] for item in items.values()),
        "items_with_growth": sum(1 for item in items.values() if item["views"] > 0),
        "measured_from": measured_from.isoformat() if measured_from else None,
        "samples": samples,
        "items": items,
    }


async def offer_analytics_today(user_id: int) -> dict[str, Any]:
    grouped, measured_from, samples = await snapshots_today(user_id, "offers")
    sent_today = read_today = ordered_today = 0
    for payloads in grouped.values():
        first_payload, last_payload = payloads[0], payloads[-1]
        sent_today += int(happened_today(last_payload.get("date_create")))
        read_today += int(not bool(first_payload.get("is_read")) and bool(last_payload.get("is_read")))
        first_orders = snapshot_number(first_payload.get("market") or {}, "buyer_order_count")
        last_orders = snapshot_number(last_payload.get("market") or {}, "buyer_order_count")
        ordered_today += int(last_orders > first_orders)
    return {
        "sent": sent_today,
        "read": read_today,
        "projects_with_new_orders": ordered_today,
        "measured_from": measured_from.isoformat() if measured_from else None,
        "samples": samples,
    }


async def item_analytics_today(user_id: int, resource: str, item_id: str) -> dict[str, Any] | None:
    local_now = datetime.now(ZoneInfo("Asia/Yekaterinburg"))
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionFactory() as db:
        rows = (await db.scalars(select(AnalyticsSnapshot).where(
            AnalyticsSnapshot.user_id == user_id,
            AnalyticsSnapshot.resource == resource,
            AnalyticsSnapshot.external_id == item_id,
            AnalyticsSnapshot.captured_at >= start,
        ).order_by(AnalyticsSnapshot.captured_at))).all()
    if not rows:
        return None
    if resource == "kworks":
        points = [{
            "at": row.captured_at.isoformat(),
            "views": snapshot_views(row.payload, "kworks"),
            "sales": snapshot_number(row.payload, "orders", "sales", "orders_count"),
            "earned": snapshot_number(row.payload, "earned", "revenue"),
        } for row in rows]
        first_point, last_point = points[0], points[-1]
        return {
            "kind": "kwork",
            "views": max(last_point["views"] - first_point["views"], 0),
            "sales": max(last_point["sales"] - first_point["sales"], 0),
            "earned": max(last_point["earned"] - first_point["earned"], 0),
            "current_views": last_point["views"],
            "current_sales": last_point["sales"],
            "points": points,
            "measured_from": rows[0].captured_at.isoformat(),
            "measured_to": rows[-1].captured_at.isoformat(),
        }
    points = [{
        "at": row.captured_at.isoformat(),
        "is_read": bool(row.payload.get("is_read")),
        "buyer_orders": snapshot_number(row.payload.get("market") or {}, "buyer_order_count"),
        "competition": snapshot_number(row.payload.get("project") or {}, "offers"),
        "is_actual": bool(row.payload.get("is_actual")),
    } for row in rows]
    first_point, last_point = points[0], points[-1]
    read_point = next((point for index, point in enumerate(points) if point["is_read"] and (index == 0 or not points[index-1]["is_read"])), None)
    return {
        "kind": "offer",
        "sent_today": happened_today(rows[-1].payload.get("date_create")),
        "read_today": bool(read_point and not first_point["is_read"]),
        "read_at": read_point["at"] if read_point and not first_point["is_read"] else None,
        "new_buyer_orders": max(last_point["buyer_orders"] - first_point["buyer_orders"], 0),
        "competition_delta": last_point["competition"] - first_point["competition"],
        "current_competition": last_point["competition"],
        "is_actual": last_point["is_actual"],
        "points": points,
        "measured_from": rows[0].captured_at.isoformat(),
        "measured_to": rows[-1].captured_at.isoformat(),
    }


async def view_deltas_today(user_id: int, resource: str) -> dict[str, int]:
    grouped, _, _ = await snapshots_today(user_id, resource)
    bounds = {item_id: [snapshot_views(payload, resource) for payload in payloads] for item_id, payloads in grouped.items()}
    return {item_id: max(values[-1]-values[0], 0) for item_id, values in bounds.items() if values}
