from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from backend.api.router import router
from backend.core.security import decrypt_token, encrypt_token
from backend.db.session import close_database, init_database
from backend.services.analytics import summarize_offers as summarize
from backend.services.synchronization import scheduler_loop, stop_syncs

@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    scheduler = asyncio.create_task(scheduler_loop(), name="kwork-scheduler")
    yield
    scheduler.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler
    await stop_syncs()
    await close_database()

def create_app() -> FastAPI:
    application = FastAPI(title="Kwork Pulse API", version="4.0", lifespan=lifespan)
    application.include_router(router)
    return application

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8080)
