from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.database import dispose_db, init_db
from app.utils.logger import get_logger, setup_logging, shutdown_logging

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    setup_logging(settings)
    for warning in settings.startup_warnings():
        log.warning("startup_warning", message=warning)
    log.info("gateway_starting", env=settings.app_env, version=app.version)

    await init_db(settings)
    app.state.http = httpx.AsyncClient(timeout=None, limits=httpx.Limits(max_connections=200))
    # TASK-06: await registry.load(app)
    try:
        yield
    finally:
        # TASK-06: await registry.close()
        await app.state.http.aclose()
        await dispose_db()
        log.info("gateway_stopped")
        shutdown_logging()
