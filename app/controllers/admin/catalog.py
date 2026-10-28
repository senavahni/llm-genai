from typing import Any

from fastapi import Request

from app.controllers.admin import actor, optional_registry, registry
from app.core.database import SessionLocal
from app.schemas.admin import (
    ModelCreate,
    ModelUpdate,
    ProviderUpdate,
    RouteCreate,
    RouteUpdate,
)
from app.schemas.common import AuthContext
from app.services import model_service as svc


async def list_providers() -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_providers(s), "next_cursor": None}


async def update_provider(
    code: str, body: ProviderUpdate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.update_provider(
            s,
            actor(request, auth),
            code,
            body,
            optional_registry(request),
            request.headers.get("if-match"),
        )


async def test_provider(code: str, request: Request) -> dict[str, Any]:
    return await svc.test_provider(code, registry(request))


async def list_models() -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_models(s), "next_cursor": None}


async def create_model(body: ModelCreate, request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.create_model(s, actor(request, auth), body, optional_registry(request))


async def update_model(
    alias: str, body: ModelUpdate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.update_model(
            s,
            actor(request, auth),
            alias,
            body,
            optional_registry(request),
            request.headers.get("if-match"),
        )


async def delete_model(alias: str, request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.delete_model(s, actor(request, auth), alias, optional_registry(request))


async def list_routes() -> dict[str, Any]:
    async with SessionLocal() as s:
        return {"data": await svc.list_routes(s), "next_cursor": None}


async def create_route(body: RouteCreate, request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.create_route(s, actor(request, auth), body, optional_registry(request))


async def update_route(
    alias: str, body: RouteUpdate, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.update_route(
            s,
            actor(request, auth),
            alias,
            body,
            optional_registry(request),
            request.headers.get("if-match"),
        )


async def delete_route(alias: str, request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await svc.delete_route(s, actor(request, auth), alias, optional_registry(request))
