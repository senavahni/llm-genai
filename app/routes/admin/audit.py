import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from app.controllers.admin import observe as c

router = APIRouter()


@router.get("/audit-logs")
async def audit_logs(
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: uuid.UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await c.audit_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        action=action,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )
