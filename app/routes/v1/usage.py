from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.controllers import usage_controller
from app.schemas.common import AuthContext
from app.utils.auth import require_scope

router = APIRouter()


@router.get("/usage")
async def usage(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    auth: AuthContext = Depends(require_scope("usage:read")),
) -> dict[str, Any]:
    return await usage_controller.get_usage(auth, start, end)
