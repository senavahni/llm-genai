import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ConfigError, Settings, get_settings
from app.core.lifespan import lifespan
from app.middlewares.body_limit import BodySizeLimitMiddleware
from app.middlewares.error_handler import register_error_handlers
from app.middlewares.request_context import RequestContextMiddleware
from app.routes import admin, health, v1

VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="LLM Gateway",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.started_at = time.monotonic()

    # add_middleware: yang terakhir ditambahkan = paling luar.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware, trust_proxy=settings.trust_proxy)

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(health.metrics_router)
    app.include_router(v1.router)
    app.include_router(admin.router)
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise SystemExit(str(exc)) from None
