from __future__ import annotations

# Compatibility entrypoint. The application now lives in backend.app.
from backend.app import create_app as create_v2_app

import os
import asyncio
from pathlib import Path
from typing import Any
from aiohttp import web
from dotenv import load_dotenv
from backend.kwork_client import KworkClient, KworkError

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"

def credentials() -> tuple[str, str, str | None]:
    load_dotenv(ROOT / ".env")
    login, password = os.getenv("KWORK_LOGIN", "").strip(), os.getenv("KWORK_PASSWORD", "")
    if not login or not password:
        raise ValueError("В .env отсутствуют KWORK_LOGIN или KWORK_PASSWORD")
    return login, password, os.getenv("KWORK_PHONE_LAST") or None

def summarize(offers: list[dict[str, Any]]) -> dict[str, int]:
    return {"total": len(offers), "read": sum(x.get("is_read") is True for x in offers),
            "unread": sum(x.get("is_read") is not True for x in offers),
            "active": sum(x.get("is_actual") is True for x in offers),
            "viewedByMe": sum(
                isinstance(x.get("project"), dict) and x["project"].get("is_viewed") is True
                for x in offers
            ),
            "withOrders": sum((x.get("market") or {}).get("buyer_order_count", 0) > 0 for x in offers),
            "buyerOrders": sum((x.get("market") or {}).get("buyer_order_count", 0) for x in offers)}

async def enrich_offers(client: KworkClient, offers: list[dict[str, Any]]) -> None:
    semaphore = asyncio.Semaphore(6)

    async def enrich(offer: dict[str, Any]) -> None:
        project = offer.get("project")
        raw_id = offer.get("want_id") or (project.get("id") if isinstance(project, dict) else None)
        if not isinstance(raw_id, int) or raw_id <= 0:
            offer["market"] = {"buyer_order_count": 0, "available": False}
            return
        try:
            async with semaphore:
                offer["market"] = {**await client.get_project_market_data(raw_id), "available": True}
        except KworkError:
            offer["market"] = {"buyer_order_count": 0, "available": False}

    await asyncio.gather(*(enrich(offer) for offer in offers))
    project_ids = [
        offer.get("want_id") for offer in offers
        if isinstance(offer.get("want_id"), int) and offer.get("want_id") > 0
    ]
    try:
        selected = await client.get_selected_orders(project_ids)
    except KworkError:
        selected = {}
    for offer in offers:
        project_id = offer.get("want_id")
        if project_id in selected:
            offer.setdefault("market", {}).update(selected[project_id])

async def offers_handler(_: web.Request) -> web.Response:
    try:
        login, password, phone_last = credentials()
        async with KworkClient(login, password, phone_last=phone_last) as client:
            offers = await client.get_all_offers()
            await enrich_offers(client, offers)
        return web.json_response({"offers": offers, "summary": summarize(offers)})
    except (KworkError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=502)

async def index_handler(_: web.Request) -> web.StreamResponse:
    if not (DIST / "index.html").exists():
        raise web.HTTPServiceUnavailable(text="Сначала соберите frontend")
    return web.FileResponse(DIST / "index.html")

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", lambda _: web.json_response({"status": "ok"}))
    app.router.add_get("/api/offers", offers_handler)
    if (DIST / "assets").exists(): app.router.add_static("/assets", DIST / "assets")
    app.router.add_get("/{tail:.*}", index_handler)
    return app

if __name__ == "__main__":
    web.run_app(create_v2_app(), host="0.0.0.0", port=8080)
