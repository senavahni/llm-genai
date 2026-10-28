import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.database import dispose_db, init_db
from app.core.registry import load_registry
from app.services.key_service import key_service
from app.services.maintenance_service import retention_forever
from app.services.ratelimit_service import ratelimit_service
from app.services.router_service import Router
from app.services.usage_service import usage_service
from app.utils.logger import get_logger, setup_logging, shutdown_logging
from app.utils.streaming import drain_finishers

log = get_logger(__name__)

ORPHAN_SWEEP_INTERVAL_S = 300


RATELIMIT_CLEANUP_INTERVAL_S = 60


async def _cleanup_ratelimit_forever() -> None:
    """Buang state rate limit key yang idle > 10 menit (memori tidak tumbuh tanpa batas)."""
    while True:
        await asyncio.sleep(RATELIMIT_CLEANUP_INTERVAL_S)
        removed = ratelimit_service.cleanup()
        if removed:
            log.debug("ratelimit_cleanup", removed=removed)


async def _sweep_orphans_forever() -> None:
    """Request `pending` > 10 menit → error `orphaned` (TASK-15), tiap 5 menit."""
    while True:
        await asyncio.sleep(ORPHAN_SWEEP_INTERVAL_S)
        try:
            await usage_service.sweep_orphans()
        except Exception as exc:  # noqa: BLE001 - DB down: coba lagi di putaran berikut
            log.warning("orphan_sweep_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    setup_logging(settings)
    for warning in settings.startup_warnings():
        log.warning("startup_warning", message=warning)
    log.info("gateway_starting", env=settings.app_env, version=app.version)

    await init_db(settings)
    registry = await load_registry(app)
    # klien httpx2 bersama (SDK openai/anthropic memakai httpx2), dimiliki registry
    app.state.http = registry.http
    # router memegang referensi registry: reload katalog langsung terlihat
    app.state.router = Router(registry)
    tasks = [
        asyncio.ensure_future(_sweep_orphans_forever()),
        asyncio.ensure_future(_cleanup_ratelimit_forever()),
        asyncio.ensure_future(retention_forever()),  # 00:30 UTC tiap hari
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        await drain_finishers()
        await key_service.drain()
        await registry.close()
        await dispose_db()
        log.info("gateway_stopped")
        shutdown_logging()
