import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.core.config import get_settings
from app.services.health_service import health_service
from app.services.key_service import key_service
from app.utils.errors import GatewayError, PermissionDenied
from app.utils.helper import client_ip

LOCALHOST = {"127.0.0.1", "::1", "localhost"}


async def _privileged(request: Request) -> bool:
    """Localhost atau membawa key admin → boleh melihat detail error / metrik."""
    if client_ip(request.scope, get_settings().trust_proxy) in LOCALHOST:
        return True
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    raw = token.strip() if scheme.lower() == "bearer" else request.headers.get("x-api-key")
    if not raw:
        return False
    try:
        return (await key_service.authenticate(raw)).is_admin
    except GatewayError:
        return False


def live(request: Request) -> dict[str, Any]:
    started = getattr(request.app.state, "started_at", None)
    return {
        "status": "ok",
        "version": request.app.version,
        "uptime_s": round(time.monotonic() - started, 1) if started else 0.0,
    }


async def ready(request: Request) -> JSONResponse:
    registry = getattr(request.app.state, "registry", None)
    status, body = await health_service.ready(registry, privileged=await _privileged(request))
    return JSONResponse(body, status_code=status)


async def metrics(request: Request) -> Response:
    if not await _privileged(request):
        raise PermissionDenied("/metrics hanya dari localhost atau dengan key admin")
    registry = getattr(request.app.state, "registry", None)
    return Response(await health_service.metrics_text(registry), media_type=CONTENT_TYPE_LATEST)
