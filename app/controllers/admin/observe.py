import uuid
from datetime import date, datetime
from typing import Any

from fastapi import Request
from pydantic import SecretStr

from app.controllers.admin import actor, optional_registry, registry
from app.core.database import SessionLocal
from app.schemas.admin import RequestFilter, UsageQuery
from app.schemas.common import AuthContext
from app.services import admin_query_service as q
from app.services import provider_billing as billing
from app.services import runtime_admin_service as rt
from app.services.context import parse_request_tags
from app.utils.errors import InvalidRequestError
from app.utils.helper import utcnow


async def list_requests(f: RequestFilter, cursor: str | None, limit: int) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await q.list_requests(s, f, cursor, limit)


async def get_request(request_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await q.get_request(s, request_id)


async def usage(
    date_from: date | None, date_to: date | None, group_by: str, project_id: uuid.UUID | None
) -> dict[str, Any]:
    to = date_to or utcnow().date()
    query = UsageQuery.model_validate(
        {
            "date_from": date_from or to.replace(day=1),
            "date_to": to,
            "group_by": group_by,
            "project_id": project_id,
        }
    )
    async with SessionLocal() as s:
        return await q.usage(s, query)


async def usage_by_tag(
    key: str,
    date_from: date | None,
    date_to: date | None,
    project_id: uuid.UUID | None,
    match: str | None,
) -> dict[str, Any]:
    """`match` = `job:abc,agent:curator` (pasangan tag yang harus cocok)."""
    tags, warnings = parse_request_tags((match or "").replace(":", "="))
    if warnings:
        raise InvalidRequestError("match harus berformat key:value,…", param="match")
    to = date_to or utcnow().date()
    start = date_from or to.replace(day=1)
    if start > to:
        raise InvalidRequestError("from harus ≤ to", param="from")
    async with SessionLocal() as s:
        return await q.usage_by_tag(
            s, key=key, date_from=start, date_to=to, project_id=project_id, match=tags
        )


PROVIDER_BILLING_MAX_DAYS = 366


async def provider_billing(
    request: Request, date_from: date | None, date_to: date | None
) -> dict[str, Any]:
    to = date_to or utcnow().date()
    start = date_from or to.replace(day=1)
    if start > to or (to - start).days >= PROVIDER_BILLING_MAX_DAYS:
        raise InvalidRequestError(
            f"rentang tanggal harus valid dan <= {PROVIDER_BILLING_MAX_DAYS} hari"
        )
    settings = request.app.state.settings
    keys = {
        "openai": _secret(settings.openai_admin_key),
        "anthropic": _secret(settings.anthropic_admin_key),
    }
    providers = await billing.provider_billing(request.app.state.http, keys, start, to)
    return {"from": start.isoformat(), "to": to.isoformat(), "providers": providers}


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() or None if value is not None else None


async def audit_logs(**filters: Any) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await q.list_audit(s, **filters)


async def runtime_status(request: Request) -> dict[str, Any]:
    return await rt.status(registry(request))


async def runtime_load(
    alias: str, pin: bool, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await rt.load(s, actor(request, auth), registry(request), alias, pin)


async def runtime_unload(
    alias: str, force: bool, request: Request, auth: AuthContext
) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await rt.unload(s, actor(request, auth), registry(request), alias, force)


async def runtime_events(**filters: Any) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await q.list_runtime_events(s, **filters)


async def swap_stats(date_from: datetime | None, date_to: datetime | None) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await q.swap_stats(s, date_from, date_to)


async def cache_reload(request: Request, auth: AuthContext) -> dict[str, Any]:
    async with SessionLocal() as s:
        return await rt.reload_caches(s, actor(request, auth), optional_registry(request))
