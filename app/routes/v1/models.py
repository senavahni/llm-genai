from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers import model_controller
from app.schemas.common import AuthContext
from app.utils.auth import require_scope

router = APIRouter()


@router.get("/models")
async def list_models(
    request: Request, auth: AuthContext = Depends(require_scope("models:read"))
) -> dict[str, Any]:
    return await model_controller.list_models(request, auth)


@router.get("/models/{model_id:path}")
async def get_model(
    model_id: str, request: Request, auth: AuthContext = Depends(require_scope("models:read"))
) -> dict[str, Any]:
    return await model_controller.get_model(model_id, request, auth)
