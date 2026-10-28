from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import catalog as c
from app.schemas.admin import RouteCreate, RouteUpdate
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/routes")
async def list_routes() -> dict[str, Any]:
    return await c.list_routes()


@router.post("/routes", status_code=201)
async def create_route(
    body: RouteCreate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.create_route(body, request, auth)


@router.patch("/routes/{alias:path}")
async def update_route(
    alias: str, body: RouteUpdate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.update_route(alias, body, request, auth)


@router.delete("/routes/{alias:path}")
async def delete_route(
    alias: str, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.delete_route(alias, request, auth)
