from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import catalog as c
from app.schemas.admin import ProviderCreate, ProviderUpdate
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    return await c.list_providers()


@router.post("/providers", status_code=201)
async def create_provider(
    body: ProviderCreate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    """Provider remote baru (OpenAI/Anthropic/Gemini-compatible), mis. DeepSeek, Groq."""
    return await c.create_provider(body, request, auth)


@router.patch("/providers/{code}")
async def update_provider(
    code: str, body: ProviderUpdate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.update_provider(code, body, request, auth)


@router.delete("/providers/{code}")
async def delete_provider(
    code: str, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.delete_provider(code, request, auth)


@router.post("/providers/{code}/test")
async def test_provider(code: str, request: Request) -> dict[str, Any]:
    return await c.test_provider(code, request)
