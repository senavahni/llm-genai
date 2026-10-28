import uuid
from typing import Any

from fastapi import Request

from app.controllers.admin import actor
from app.core.database import SessionLocal
from app.schemas.admin import (
    AllowedModelsSet,
    KeyCreate,
    ProjectCreate,
    ProjectUpdate,
    QuotasSet,
)
from app.schemas.common import AuthContext
from app.services import project_service as svc


async def list_projects() -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_projects(s), "next_cursor": None}


async def get_project(project_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.get_project(s, project_id)


async def create_project(
    body: ProjectCreate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.create_project(s, actor(request, auth), body)


async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.update_project(
            s, actor(request, auth), project_id, body, request.headers.get("if-match")
        )


async def archive_project(
    project_id: uuid.UUID, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.archive_project(s, actor(request, auth), project_id)


async def set_allowed_models(
    project_id: uuid.UUID, body: AllowedModelsSet, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.set_allowed_models(s, actor(request, auth), project_id, body)


async def list_keys(project_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_keys(s, project_id), "next_cursor": None}


async def create_key(
    project_id: uuid.UUID, body: KeyCreate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.create_key(s, actor(request, auth), project_id, body)


async def revoke_key(
    key_id: uuid.UUID, reason: str, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.revoke_key(s, actor(request, auth), key_id, reason)


async def rotate_key(key_id: uuid.UUID, request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.rotate_key(s, actor(request, auth), key_id)


async def list_quotas(project_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_quotas(s, project_id), "next_cursor": None}


async def set_quotas(
    project_id: uuid.UUID, body: QuotasSet, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.set_quotas(s, actor(request, auth), project_id, body)}
