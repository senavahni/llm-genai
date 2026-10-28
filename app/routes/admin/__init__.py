from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.controllers import admin_usage_controller
from app.utils.auth import require_admin

# Endpoint admin lain diisi di TASK-17. Seluruh /admin/* wajib role admin.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/usage/verify")
async def usage_verify(day: date | None = Query(default=None)) -> dict[str, Any]:
    return await admin_usage_controller.verify_usage(day)
