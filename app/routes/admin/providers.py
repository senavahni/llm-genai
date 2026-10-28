from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import catalog as c
from app.schemas.admin import ProviderUpdate
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    return await c.list_providers()


@router.patch("/providers/{code}")
async def update_provider(
    code: str, body: ProviderUpdate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.update_provider(code, body, request, auth)


@router.post("/providers/{code}/test")
async def test_provider(code: str, request: Request) -> dict[str, Any]:
    return await c.test_provider(code, request)
