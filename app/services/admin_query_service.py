"""Admin read-only: penelusuran request, usage agregat, audit log, runtime events & swap-stats
(TASK-17). Paginasi cursor stabil (`created_at,id`), limit ≤ 200."""

import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Project, Request, RequestAttempt, RuntimeEvent, UsageDaily
from app.models.request import RequestPayload
from app.schemas.admin import RequestFilter, UsageQuery
from app.utils.errors import InvalidRequestError, NotFound
from app.utils.helper import utcnow

MAX_LIMIT = 200


def encode_cursor(ts: datetime, ident: Any) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{ident}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, _, ident = raw.partition("|")
        return datetime.fromisoformat(ts), ident
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidRequestError("cursor tidak valid", param="cursor") from exc


def _limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidRequestError(f"limit harus 1–{MAX_LIMIT}", param="limit")
    return limit


def _jsonable(row: Any, columns: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in columns:
        v = getattr(row, c)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif v is not None and type(v).__name__ == "Decimal":
            v = str(v)
        elif v is not None and type(v).__name__ in ("IPv4Address", "IPv6Address"):
            v = str(v)
        out[c] = v
    return out


REQUEST_COLUMNS = [c.name for c in Request.__table__.columns]
ATTEMPT_COLUMNS = [c.name for c in RequestAttempt.__table__.columns if c.name != "request_id"]
AUDIT_COLUMNS = [c.name for c in AuditLog.__table__.columns]
EVENT_COLUMNS = [c.name for c in RuntimeEvent.__table__.columns]


async def _page(
    session: AsyncSession,
    stmt: Select[Any],
    ts_col: Any,
    id_col: Any,
    cursor: str | None,
    limit: int,
    id_type: type = uuid.UUID,
) -> tuple[list[Any], str | None]:
    limit = _limit(limit)
    if cursor:
        ts, ident = decode_cursor(cursor)
        stmt = stmt.where(tuple_(ts_col, id_col) < tuple_(ts, id_type(ident)))
    rows = list(
        (
            await session.execute(stmt.order_by(ts_col.desc(), id_col.desc()).limit(limit + 1))
        ).scalars()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(getattr(last, ts_col.key), getattr(last, id_col.key))
    return rows, next_cursor


# ------------------------------------------------------------------ requests
async def list_requests(
    session: AsyncSession, f: RequestFilter, cursor: str | None, limit: int
) -> dict[str, Any]:
    stmt = select(Request)
    conditions = {
        Request.project_id: f.project_id,
        Request.api_key_id: f.api_key_id,
        Request.status: f.status,
        Request.endpoint: f.endpoint,
        Request.requested_model: f.requested_model,
        Request.provider_code: f.provider_code,
        Request.device: f.device,
        Request.caller_task: f.caller_task,
        Request.caller_agent: f.caller_agent,
    }
    for col, value in conditions.items():
        if value is not None:
            stmt = stmt.where(col == value)
    if f.date_from:
        stmt = stmt.where(Request.created_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Request.created_at < f.date_to)
    rows, nxt = await _page(session, stmt, Request.created_at, Request.id, cursor, limit)
    return {"data": [_jsonable(r, REQUEST_COLUMNS) for r in rows], "next_cursor": nxt}


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> dict[str, Any]:
    req = await session.get(Request, request_id)
    if req is None:
        raise NotFound(f"Request {request_id} tidak ditemukan", param="request_id")
    attempts = (
        await session.execute(
            select(RequestAttempt)
            .where(RequestAttempt.request_id == request_id)
            .order_by(RequestAttempt.attempt_no)
        )
    ).scalars()
    payload = (
        await session.execute(
            select(RequestPayload).where(
                RequestPayload.request_id == request_id, RequestPayload.expires_at > utcnow()
            )
        )
    ).scalar_one_or_none()
    return {
        **_jsonable(req, REQUEST_COLUMNS),
        "attempt_rows": [_jsonable(a, ATTEMPT_COLUMNS) for a in attempts],
        "payload": {
            "request_body": payload.request_body,
            "response_body": payload.response_body,
            "expires_at": payload.expires_at.isoformat(),
        }
        if payload
        else None,
    }


# --------------------------------------------------------------------- usage
async def usage(session: AsyncSession, q: UsageQuery) -> dict[str, Any]:
    group_col = {
        "day": UsageDaily.day,
        "project": Project.slug,
        "model": UsageDaily.model_alias,
        "provider": UsageDaily.provider_code,
    }[q.group_by]
    stmt = (
        select(
            group_col.label("key"),
            func.sum(UsageDaily.request_count),
            func.sum(UsageDaily.success_count),
            func.sum(UsageDaily.error_count),
            func.sum(UsageDaily.prompt_tokens),
            func.sum(UsageDaily.completion_tokens),
            func.sum(UsageDaily.image_count),
            func.sum(UsageDaily.cost_usd),
        )
        .join(Project, Project.id == UsageDaily.project_id)
        .where(UsageDaily.day >= q.date_from, UsageDaily.day <= q.date_to)
        .group_by(group_col)
        .order_by(group_col)
    )
    if q.project_id:
        stmt = stmt.where(UsageDaily.project_id == q.project_id)
    rows = (await session.execute(stmt)).all()
    return {
        "group_by": q.group_by,
        "from": q.date_from.isoformat(),
        "to": q.date_to.isoformat(),
        "data": [
            {
                q.group_by: str(r[0]),
                "requests": int(r[1] or 0),
                "success": int(r[2] or 0),
                "errors": int(r[3] or 0),
                "prompt_tokens": int(r[4] or 0),
                "completion_tokens": int(r[5] or 0),
                "image_count": int(r[6] or 0),
                "cost_usd": str(r[7] or 0),
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------- audit
async def list_audit(
    session: AsyncSession,
    *,
    entity_type: str | None,
    entity_id: str | None,
    actor: uuid.UUID | None,
    action: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    stmt = select(AuditLog)
    for col, value in (
        (AuditLog.entity_type, entity_type),
        (AuditLog.entity_id, entity_id),
        (AuditLog.actor_key_id, actor),
        (AuditLog.action, action),
    ):
        if value is not None:
            stmt = stmt.where(col == value)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at < date_to)
    rows, nxt = await _page(
        session, stmt, AuditLog.created_at, AuditLog.id, cursor, limit, id_type=int
    )
    return {"data": [_jsonable(r, AUDIT_COLUMNS) for r in rows], "next_cursor": nxt}


# ------------------------------------------------------------ runtime events
async def list_runtime_events(
    session: AsyncSession,
    *,
    model: str | None,
    device: str | None,
    event: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    stmt = select(RuntimeEvent)
    for col, value in (
        (RuntimeEvent.model_alias, model),
        (RuntimeEvent.device, device),
        (RuntimeEvent.event, event),
    ):
        if value is not None:
            stmt = stmt.where(col == value)
    if date_from:
        stmt = stmt.where(RuntimeEvent.created_at >= date_from)
    if date_to:
        stmt = stmt.where(RuntimeEvent.created_at < date_to)
    rows, nxt = await _page(
        session, stmt, RuntimeEvent.created_at, RuntimeEvent.id, cursor, limit, id_type=int
    )
    return {"data": [_jsonable(r, EVENT_COLUMNS) for r in rows], "next_cursor": nxt}


async def swap_stats(
    session: AsyncSession, date_from: datetime | None, date_to: datetime | None
) -> dict[str, Any]:
    """Jumlah load/evict per model, rata-rata durasi, dan model pemicu thrashing teratas."""
    where: list[ColumnElement[bool]] = [
        RuntimeEvent.event.in_(("load", "evict", "unload", "oom", "compile"))
    ]
    if date_from:
        where.append(RuntimeEvent.created_at >= date_from)
    if date_to:
        where.append(RuntimeEvent.created_at < date_to)
    rows = (
        await session.execute(
            select(
                RuntimeEvent.model_alias,
                RuntimeEvent.device,
                RuntimeEvent.event,
                func.count(),
                func.avg(RuntimeEvent.duration_ms),
            )
            .where(and_(*where))
            .group_by(RuntimeEvent.model_alias, RuntimeEvent.device, RuntimeEvent.event)
        )
    ).all()
    per_model: dict[str, dict[str, Any]] = {}
    for alias, device, event, count, avg in rows:
        entry = per_model.setdefault(str(alias), {"model": alias, "device": device})
        entry[f"{event}_count"] = int(count)
        entry[f"{event}_avg_ms"] = round(float(avg), 1) if avg is not None else None
    # pemicu thrashing = evict yang reason-nya 'lru_evict_for:<model>' terbanyak
    triggers = (
        await session.execute(
            select(RuntimeEvent.reason, func.count())
            .where(
                and_(*where),
                RuntimeEvent.event == "evict",
                or_(RuntimeEvent.reason.like("lru_evict_for:%")),
            )
            .group_by(RuntimeEvent.reason)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    return {
        "models": sorted(per_model.values(), key=lambda m: -(m.get("load_count") or 0)),
        "top_thrashing_triggers": [
            {"model": str(r).removeprefix("lru_evict_for:"), "evictions_caused": int(c)}
            for r, c in triggers
        ],
    }
