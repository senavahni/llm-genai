import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import projects as c
from app.schemas.admin import KeyCreate, KeyRevoke
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/projects/{project_id}/keys")
async def list_keys(project_id: uuid.UUID) -> dict[str, Any]:
    return await c.list_keys(project_id)


@router.post("/projects/{project_id}/keys", status_code=201)
async def create_key(
    project_id: uuid.UUID,
    body: KeyCreate,
    request: Request,
    auth: AuthContext = Depends(require_admin),
) -> dict[str, Any]:
    return await c.create_key(project_id, body, request, auth)


@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: uuid.UUID, body: KeyRevoke, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.revoke_key(key_id, body.reason, request, auth)


@router.post("/keys/{key_id}/rotate")
async def rotate_key(
    key_id: uuid.UUID, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.rotate_key(key_id, request, auth)
