from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import observe as c
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.post("/cache/reload")
async def cache_reload(
    request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.cache_reload(request, auth)
