import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import projects as c
from app.schemas.admin import QuotasSet
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/projects/{project_id}/quotas")
async def list_quotas(project_id: uuid.UUID) -> dict[str, Any]:
    return await c.list_quotas(project_id)


@router.put("/projects/{project_id}/quotas")
async def set_quotas(
    project_id: uuid.UUID,
    body: QuotasSet,
    request: Request,
    auth: AuthContext = Depends(require_admin),
) -> dict[str, Any]:
    return await c.set_quotas(project_id, body, request, auth)
