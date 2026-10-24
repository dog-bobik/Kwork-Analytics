from __future__ import annotations
import asyncio
from contextlib import suppress
from typing import Any
from backend.core.config import settings
from backend.core.security import decrypt_token
from backend.db import repositories
from backend.kwork_client import KworkClient, KworkError

ACTIVE_SYNCS: dict[int, asyncio.Task[None]] = {}

async def enrich_offers(client: KworkClient, offers: list[dict[str, Any]]) -> None:
    """Server-only enrichment. Browser requests can never invoke this function."""
    project_ids = [item.get("want_id") for item in offers if isinstance(item.get("want_id"), int)]
    try:
        selected = await client.get_selected_orders(project_ids)
    except KworkError:
        selected = {}
    for offer in offers:
        project_id = offer.get("want_id")
        offer["market"] = {"buyer_order_count": 0, "available": False}
        if project_id in selected:
            offer["market"].update(selected[project_id])

async def sync_user(user_id: int) -> None:
    user = await repositories.get_user(user_id)
    if user is None:
        return
    try:
        async with KworkClient(token=decrypt_token(user.token_encrypted), timeout_seconds=45) as client:
            actor = await client.get_actor()
            kwork_user_id = int(actor.get("id") or actor.get("USERID") or actor.get("user_id"))
            offers, kworks, reviews = await asyncio.gather(
                client.get_all_offers(), client.get_all_kworks(actor=actor), client.get_all_user_reviews(kwork_user_id)
            )
            await enrich_offers(client, offers)
        await repositories.save_sync(user_id, offers, kworks, reviews, actor)
    except (KworkError, ValueError, OSError) as error:
        await repositories.record_sync_error(user_id, str(error))

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

async def scheduler_loop() -> None:
    while True:
        try:
            for user_id in await repositories.users_due(settings.sync_interval_seconds):
                schedule_sync(user_id)
        except Exception:
            pass
        await asyncio.sleep(60)

async def stop_syncs() -> None:
    for task in list(ACTIVE_SYNCS.values()):
        task.cancel()
    if ACTIVE_SYNCS:
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*list(ACTIVE_SYNCS.values()), return_exceptions=True)

def sync_meta(user) -> dict[str, Any]:
    return {"syncing": user.id in ACTIVE_SYNCS, "last_sync_at": user.last_sync_at.isoformat() if user.last_sync_at else None, "sync_error": user.sync_error, "interval_seconds": settings.sync_interval_seconds}
