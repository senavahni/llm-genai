import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.controllers.admin import projects as c
from app.schemas.admin import AllowedModelsSet, ProjectCreate, ProjectUpdate
from app.schemas.common import AuthContext
from app.utils.auth import require_admin

router = APIRouter()


@router.get("/projects")
async def list_projects() -> dict[str, Any]:
    return await c.list_projects()


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.create_project(body, request, auth)


@router.get("/projects/{project_id}")
async def get_project(project_id: uuid.UUID) -> dict[str, Any]:
    return await c.get_project(project_id)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    request: Request,
    auth: AuthContext = Depends(require_admin),
) -> dict[str, Any]:
    return await c.update_project(project_id, body, request, auth)


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: uuid.UUID, request: Request, auth: AuthContext = Depends(require_admin)
) -> dict[str, Any]:
    return await c.archive_project(project_id, request, auth)


@router.put("/projects/{project_id}/allowed-models")
async def set_allowed_models(
    project_id: uuid.UUID,
    body: AllowedModelsSet,
    request: Request,
    auth: AuthContext = Depends(require_admin),
) -> dict[str, Any]:
    return await c.set_allowed_models(project_id, body, request, auth)
