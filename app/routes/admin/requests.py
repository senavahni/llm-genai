import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from app.controllers.admin import observe as c
from app.schemas.admin import RequestFilter

router = APIRouter()


@router.get("/requests")
async def list_requests(
    project_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    status: str | None = None,
    endpoint: str | None = None,
    model: str | None = Query(default=None, description="requested_model"),
    provider: str | None = None,
    device: str | None = None,
    caller_task: str | None = None,
    caller_agent: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    f = RequestFilter(
        project_id=project_id,
        api_key_id=api_key_id,
        status=status,
        endpoint=endpoint,
        requested_model=model,
        provider_code=provider,
        device=device,
        caller_task=caller_task,
        caller_agent=caller_agent,
        date_from=date_from,
        date_to=date_to,
    )
    return await c.list_requests(f, cursor, limit)


@router.get("/requests/{request_id}")
async def get_request(request_id: uuid.UUID) -> dict[str, Any]:
    return await c.get_request(request_id)
