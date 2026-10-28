"""FastAPI dependencies untuk autentikasi API key gateway."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Depends, Request

from app.schemas.common import AuthContext
from app.services.key_service import key_service
from app.utils.errors import AuthenticationError, PermissionDenied


def _raw_key(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return request.headers.get("x-api-key")


async def get_auth(request: Request) -> AuthContext:
    raw = _raw_key(request)
    if not raw:
        raise AuthenticationError("API key tidak ada (Authorization: Bearer ... atau x-api-key)")
    ctx = await key_service.authenticate(raw)
    request.state.auth = ctx
    structlog.contextvars.bind_contextvars(project_slug=ctx.project_slug, key_prefix=ctx.key_prefix)
    return ctx


def require_scope(scope: str) -> Callable[..., Awaitable[AuthContext]]:
    # scope valid: chat, completions, embeddings, images, models:read, usage:read
    async def _dependency(ctx: AuthContext = Depends(get_auth)) -> AuthContext:
        if scope not in ctx.scopes:
            raise PermissionDenied(f"API key tidak memiliki scope '{scope}'")
        return ctx

    return _dependency


async def require_admin(ctx: AuthContext = Depends(get_auth)) -> AuthContext:
    if not ctx.is_admin:
        raise PermissionDenied("Endpoint ini hanya untuk key dengan role admin")
    return ctx
