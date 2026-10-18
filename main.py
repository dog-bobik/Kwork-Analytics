from __future__ import annotations

import asyncio
import json
import os
import sys
from dotenv import load_dotenv

from backend.kwork_client import KworkClient, KworkError


def _credentials() -> tuple[str, str, str | None]:
    load_dotenv()
    login = os.getenv("KWORK_LOGIN", "").strip()
    password = os.getenv("KWORK_PASSWORD", "")
    phone_last = os.getenv("KWORK_PHONE_LAST") or None
    if not login or not password:
        raise ValueError("Добавьте KWORK_LOGIN и KWORK_PASSWORD в файл .env")
    return login, password, phone_last


async def run() -> int:
    login, password, phone_last = _credentials()
    try:
        async with KworkClient(login, password, phone_last=phone_last) as client:
            offers = await client.get_all_offers()
    except (KworkError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    print(f"Откликов найдено: {len(offers)}")
    print(json.dumps(offers, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
