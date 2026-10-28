from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.controllers.admin import observe as c
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/runtime/status")
async def runtime_status(request: Request) -> dict[str, Any]:
    return await c.runtime_status(request)


@router.post("/runtime/models/{alias:path}/load")
async def runtime_load(
    alias: str, request: Request, pin: bool = False, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.runtime_load(alias, pin, request, auth)


@router.post("/runtime/models/{alias:path}/unload")
async def runtime_unload(
    alias: str, request: Request, force: bool = False, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.runtime_unload(alias, force, request, auth)


@router.get("/runtime/events")
async def runtime_events(
    model: str | None = None,
    device: str | None = None,
    event: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await c.runtime_events(
        model=model,
        device=device,
        event=event,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/runtime/swap-stats")
async def swap_stats(
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    return await c.swap_stats(date_from, date_to)
