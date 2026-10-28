import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query

from app.controllers import admin_usage_controller
from app.controllers.admin import observe as c

router = APIRouter()


@router.get("/usage")
async def usage(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    group_by: Literal["day", "project", "model", "provider"] = "day",
    project_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await c.usage(date_from, date_to, group_by, project_id)


@router.get("/usage/verify")
async def usage_verify(day: date | None = Query(default=None)) -> dict[str, Any]:
    return await admin_usage_controller.verify_usage(day)
