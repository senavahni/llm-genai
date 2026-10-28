"""Controller Admin API (TASK-17): bangun Actor (audit), buka session, panggil service."""

from typing import Any

from fastapi import Request

from app.core.config import get_settings
from app.schemas.common import AuthContext
from app.services.audit_service import Actor
from app.utils.errors import ServiceUnavailable
from app.utils.helper import client_ip


def actor(request: Request, auth: AuthContext) -> Actor:
    state = request.scope.get("state") or {}
    return Actor(
        auth=auth,
        ip=client_ip(request.scope, get_settings().trust_proxy) or None,
        request_id=state.get("request_id"),
    )


def registry(request: Request) -> Any:
    reg = getattr(request.app.state, "registry", None)
    if reg is None:
        raise ServiceUnavailable("Registry gateway belum termuat")
    return reg


def optional_registry(request: Request) -> Any:
    return getattr(request.app.state, "registry", None)
