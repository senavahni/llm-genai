from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.controllers import health_controller as c

# tanpa auth (dipakai script start, Traefik, pemantauan); detail hanya untuk localhost/admin
router = APIRouter(prefix="/health", tags=["health"])
metrics_router = APIRouter(tags=["metrics"])


@router.get("/live")
def live(request: Request) -> dict[str, Any]:
    return c.live(request)


@router.get("/ready", response_model=None)
async def ready(request: Request) -> JSONResponse:
    return await c.ready(request)


@metrics_router.get("/metrics", response_model=None)
async def metrics(request: Request) -> Response:
    return await c.metrics(request)
