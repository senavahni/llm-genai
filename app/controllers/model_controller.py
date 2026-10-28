from typing import Any

from fastapi import Request

from app.controllers.common import get_router
from app.schemas.common import AuthContext
from app.schemas.converters import model_object, route_object
from app.utils.errors import ModelNotFound
from app.utils.helper import glob_match


def _allowed(alias: str, auth: AuthContext) -> bool:
    return any(glob_match(p, alias) for p in auth.allowed_models)


def _objects(request: Request, auth: AuthContext) -> dict[str, dict[str, Any]]:
    """Model & route yang diizinkan project (route hanya bila punya target yang diizinkan)."""
    catalog = get_router(request).registry.catalog
    out: dict[str, dict[str, Any]] = {}
    for alias, model in catalog.models.items():
        if model.is_enabled and _allowed(alias, auth):
            out[alias] = model_object(model)
    for alias, route in catalog.routes.items():
        if not route.is_enabled or not _allowed(alias, auth):
            continue
        targets = [
            m
            for t in route.targets
            if (m := catalog.models.get(t.model_alias)) is not None
            and m.is_enabled
            and _allowed(m.alias, auth)
        ]
        if targets:
            out[alias] = route_object(route, targets)
    return out


async def list_models(request: Request, auth: AuthContext) -> dict[str, Any]:
    objects = _objects(request, auth)
    return {"object": "list", "data": [objects[k] for k in sorted(objects)]}


async def get_model(model_id: str, request: Request, auth: AuthContext) -> dict[str, Any]:
    obj = _objects(request, auth).get(model_id)
    if obj is None:
        raise ModelNotFound(f"Model '{model_id}' tidak ditemukan")
    return obj
