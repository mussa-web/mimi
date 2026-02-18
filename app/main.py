import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.inventory import router as inventory_router
from app.core.config import settings
from app.db.database import SessionLocal
from app.services.cleanup import cleanup_stale_unverified_pending_users


async def _cleanup_worker() -> None:
    while True:
        db = SessionLocal()
        try:
            deleted = cleanup_stale_unverified_pending_users(db)
            if deleted:
                print(f"[cleanup] removed stale pending users: {deleted}")
        except Exception as exc:
            print(f"[cleanup] error: {exc}")
        finally:
            db.close()
        await asyncio.sleep(max(60, settings.cleanup_interval_minutes * 60))


@asynccontextmanager
async def lifespan(_: FastAPI):
    task: asyncio.Task | None = None
    if settings.cleanup_enabled:
        task = asyncio.create_task(_cleanup_worker())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(inventory_router)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok"}
