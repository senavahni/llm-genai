"""Audit log admin (TASK-17): dicatat di service layer dalam transaksi yang SAMA dengan perubahan
data (atomic: rollback → audit ikut batal). before/after = snapshot `*Out` (tanpa secret)."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.schemas.common import AuthContext

ACTIONS = frozenset(
    {
        "project.create",
        "project.update",
        "project.archive",
        "project.allowed_models.set",
        "key.create",
        "key.revoke",
        "key.rotate",
        "provider.update",
        "model.create",
        "model.update",
        "model.delete",
        "route.create",
        "route.update",
        "route.delete",
        "quota.set",
        "cache.reload",
        "maintenance.retention",
        "runtime.load",
        "runtime.unload",
        "model.pin",
        "model.unpin",
    }
)
# nama field persis (bukan substring: `max_tokens` bukan secret); `key` = full key sekali tampil
_SECRET_KEYS = frozenset(
    {"key", "key_hash", "api_key", "secret", "password", "runtime_token", "authorization"}
)


@dataclass(frozen=True, slots=True)
class Actor:
    auth: AuthContext | None  # None = sistem
    ip: str | None = None
    request_id: str | None = None


def _scrub(value: Any) -> Any:
    """Jaring pengaman: buang field berbau secret walau snapshot seharusnya sudah aman."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: Any,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    if action not in ACTIONS:
        raise ValueError(f"audit action tidak dikenal: {action}")
    row = AuditLog(
        actor_key_id=actor.auth.key_id if actor.auth else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_scrub(before),
        after=_scrub(after),
        ip=actor.ip,
        request_id=uuid.UUID(actor.request_id) if actor.request_id else None,
    )
    session.add(row)
    return row
