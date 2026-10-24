from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.db.models import AnalyticsSnapshot
from backend.db.session import SessionFactory


def summarize_offers(offers: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(offers),
        "read": sum(item.get("is_read") is True for item in offers),
        "unread": sum(item.get("is_read") is not True for item in offers),
        "active": sum(item.get("is_actual") is True for item in offers),
        "viewedByMe": sum(isinstance(item.get("project"), dict) and item["project"].get("is_viewed") is True for item in offers),
        "withOrders": sum((item.get("market") or {}).get("buyer_order_count", 0) > 0 for item in offers),
        "buyerOrders": sum((item.get("market") or {}).get("buyer_order_count", 0) for item in offers),
    }


def snapshot_views(payload: dict[str, Any], resource: str = "kworks") -> int:
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


async def snapshots_today(user_id: int, resource: str):
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
    return grouped, rows[0].captured_at if rows else None, len(rows), rows


async def kwork_analytics_today(user_id: int) -> dict[str, Any]:
    grouped, measured_from, samples, _ = await snapshots_today(user_id, "kworks")
    items = {}
    for item_id, payloads in grouped.items():
        first_payload, last_payload = payloads[0], payloads[-1]
        items[item_id] = {
            "views": max(snapshot_views(last_payload) - snapshot_views(first_payload), 0),
            "sales": max(snapshot_number(last_payload, "orders", "sales", "orders_count") - snapshot_number(first_payload, "orders", "sales", "orders_count"), 0),
            "earned": max(snapshot_number(last_payload, "earned", "revenue") - snapshot_number(first_payload, "earned", "revenue"), 0),
        }
    return {"views": sum(x["views"] for x in items.values()), "sales": sum(x["sales"] for x in items.values()), "earned": sum(x["earned"] for x in items.values()), "items_with_growth": sum(x["views"] > 0 for x in items.values()), "measured_from": measured_from.isoformat() if measured_from else None, "samples": samples, "items": items}


async def offer_analytics_today(user_id: int) -> dict[str, Any]:
    grouped, measured_from, samples, _ = await snapshots_today(user_id, "offers")
    sent = read = ordered = 0
    for payloads in grouped.values():
        first_payload, last_payload = payloads[0], payloads[-1]
        sent += int(happened_today(last_payload.get("date_create")))
        read += int(not bool(first_payload.get("is_read")) and bool(last_payload.get("is_read")))
        ordered += int(snapshot_number(last_payload.get("market") or {}, "buyer_order_count") > snapshot_number(first_payload.get("market") or {}, "buyer_order_count"))
    return {"sent": sent, "read": read, "projects_with_new_orders": ordered, "measured_from": measured_from.isoformat() if measured_from else None, "samples": samples}


async def item_analytics_today(user_id: int, resource: str, item_id: str) -> dict[str, Any] | None:
    _, _, _, all_rows = await snapshots_today(user_id, resource)
    rows = [row for row in all_rows if row.external_id == item_id]
    if not rows:
        return None
    if resource == "kworks":
        points = [{"at": row.captured_at.isoformat(), "views": snapshot_views(row.payload), "sales": snapshot_number(row.payload, "orders", "sales", "orders_count"), "earned": snapshot_number(row.payload, "earned", "revenue")} for row in rows]
        first, last = points[0], points[-1]
        return {"kind": "kwork", "views": max(last["views"]-first["views"], 0), "sales": max(last["sales"]-first["sales"], 0), "earned": max(last["earned"]-first["earned"], 0), "current_views": last["views"], "current_sales": last["sales"], "points": points, "measured_from": rows[0].captured_at.isoformat(), "measured_to": rows[-1].captured_at.isoformat()}
    points = [{"at": row.captured_at.isoformat(), "is_read": bool(row.payload.get("is_read")), "buyer_orders": snapshot_number(row.payload.get("market") or {}, "buyer_order_count"), "competition": snapshot_number(row.payload.get("project") or {}, "offers"), "is_actual": bool(row.payload.get("is_actual"))} for row in rows]
    first, last = points[0], points[-1]
    read_point = next((point for index, point in enumerate(points) if point["is_read"] and (index == 0 or not points[index-1]["is_read"])), None)
    return {"kind": "offer", "sent_today": happened_today(rows[-1].payload.get("date_create")), "read_today": bool(read_point and not first["is_read"]), "read_at": read_point["at"] if read_point and not first["is_read"] else None, "new_buyer_orders": max(last["buyer_orders"]-first["buyer_orders"], 0), "competition_delta": last["competition"]-first["competition"], "current_competition": last["competition"], "is_actual": last["is_actual"], "points": points, "measured_from": rows[0].captured_at.isoformat(), "measured_to": rows[-1].captured_at.isoformat()}
