from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import catalog as c
from app.schemas.admin import ModelCreate, ModelUpdate
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/models")
async def list_models() -> dict[str, Any]:
    return await c.list_models()


@router.post("/models", status_code=201)
async def create_model(
    body: ModelCreate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.create_model(body, request, auth)


# alias model memuat "/" (mis. local/qwen2.5-7b) → path converter
@router.patch("/models/{alias:path}")
async def update_model(
    alias: str, body: ModelUpdate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.update_model(alias, body, request, auth)


@router.delete("/models/{alias:path}")
async def delete_model(
    alias: str, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.delete_model(alias, request, auth)
