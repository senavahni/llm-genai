from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.database import dispose_db, init_db
from app.core.registry import load_registry
from app.services.key_service import key_service
from app.utils.logger import get_logger, setup_logging, shutdown_logging
from app.utils.streaming import drain_finishers

log = get_logger(__name__)


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
    try:
        yield
    finally:
        await drain_finishers()
        await key_service.drain()
        await registry.close()
        await dispose_db()
        log.info("gateway_stopped")
        shutdown_logging()
