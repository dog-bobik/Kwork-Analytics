from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    app_secret: str
    sync_interval_seconds: int
    session_days: int
    session_cookie: str
    cookie_secure: bool


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://kwork:kwork@127.0.0.1:5432/kwork_analytics",
        ),
        app_secret=os.getenv("APP_SECRET", "kwork-pulse-local-server-secret"),
        # Синхронизация управляется сервером, а не действиями пользователя.
        sync_interval_seconds=max(int(os.getenv("SYNC_INTERVAL_SECONDS", "3600")), 300),
        session_days=max(int(os.getenv("SESSION_DAYS", "30")), 1),
        session_cookie="kwork_pulse_session",
        cookie_secure=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
    )


settings = load_settings()
