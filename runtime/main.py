from fastapi import FastAPI

from app.core.config import ConfigError, Settings, get_settings
from app.middlewares.body_limit import BodySizeLimitMiddleware
from app.middlewares.error_handler import register_error_handlers
from app.middlewares.request_context import RequestContextMiddleware
from runtime.core.lifespan import lifespan
from runtime.routes import health, runtime, v1

VERSION = "0.1.0"


def create_runtime_app(settings: Settings | None = None, *, with_lifespan: bool = True) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="LLM Gateway — Local Runtime",
        version=VERSION,
        lifespan=lifespan if with_lifespan else None,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    # X-Request-ID dari gateway dipakai ulang → log gateway & runtime bisa dikorelasikan
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1.router)
    app.include_router(runtime.router)
    app.include_router(runtime.metrics_router)
    return app


try:
    app = create_runtime_app()
except ConfigError as exc:
    raise SystemExit(str(exc)) from None
