import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

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


@router.get("/provider-billing")
async def provider_billing(
    request: Request,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """Biaya & usage aktual dari Costs/Usage API OpenAI & Anthropic (butuh *_ADMIN_KEY)."""
    return await c.provider_billing(request, date_from, date_to)


@router.get("/usage/verify")
async def usage_verify(day: date | None = Query(default=None)) -> dict[str, Any]:
    return await admin_usage_controller.verify_usage(day)
