from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.config import settings
from backend.db.models import Base

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # Идемпотентные миграции существующей production-базы.
        await connection.execute(text("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS app_users_login_idx ON app_users(login)"))
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS status VARCHAR(32)"))
        await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS error TEXT"))
        await connection.execute(text("ALTER TABLE analytics_snapshots ADD COLUMN IF NOT EXISTS user_id BIGINT"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS sync_runs_user_id_idx ON sync_runs(user_id)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS analytics_snapshots_user_id_idx ON analytics_snapshots(user_id)"))
        # Удаляем бесполезные данные портфолио и старый кеш чужих профилей.
        await connection.execute(text("DELETE FROM current_items WHERE resource IN ('portfolio', 'profiles')"))
        await connection.execute(text("DELETE FROM analytics_snapshots WHERE resource IN ('portfolio', 'profiles')"))


async def close_database() -> None:
    await engine.dispose()
