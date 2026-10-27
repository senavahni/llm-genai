"""Autentikasi API key per project: lookup via prefix (cache TTL), verifikasi HMAC, scope, role."""

import asyncio
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.api_key import KEY_ROLES, VALID_SCOPES, ApiKey
from app.models.project import Project
from app.schemas.common import AuthContext
from app.utils import crypto
from app.utils.errors import AuthenticationError, InvalidRequestError, NotFound, ProjectSuspended
from app.utils.helper import utcnow
from app.utils.logger import get_logger

log = get_logger(__name__)

CACHE_TTL_S = 60.0
LAST_USED_THROTTLE_S = 60.0
_INVALID = "Invalid API key"


@dataclass(frozen=True, slots=True)
class _CachedKey:
    """Snapshot baris api_keys + projects (bukan objek ORM, aman dipakai lintas session)."""

    key_id: uuid.UUID
    key_prefix: str
    key_hash: str
    role: str
    scopes: frozenset[str]
    status: str
    expires_at: datetime | None
    rpm_limit: int | None
    tpm_limit: int | None
    project_id: uuid.UUID | None
    project_slug: str | None
    project_status: str | None
    log_payloads: bool
    payload_retention_days: int


class KeyService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
        *,
        cache_ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self._session_factory = session_factory
        self._cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[_CachedKey, float]] = {}
        self._last_used: dict[str, float] = {}
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ cache
    def invalidate(self, prefix: str | None = None) -> None:
        """Buang cache satu prefix (revoke/rotate/update) atau seluruh cache (prefix=None)."""
        if prefix is None:
            self._cache.clear()
        else:
            self._cache.pop(prefix, None)

    async def _lookup(self, prefix: str) -> _CachedKey | None:
        now = time.monotonic()
        hit = self._cache.get(prefix)
        if hit and hit[1] > now:
            return hit[0]

        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(ApiKey, Project)
                    .outerjoin(Project, ApiKey.project_id == Project.id)
                    .where(ApiKey.key_prefix == prefix)
                )
            ).first()
        if row is None:
            self._cache.pop(prefix, None)
            return None

        key, project = row
        entry = _CachedKey(
            key_id=key.id,
            key_prefix=key.key_prefix,
            key_hash=key.key_hash,
            role=key.role,
            scopes=frozenset(key.scopes or ()),
            status=key.status,
            expires_at=key.expires_at,
            rpm_limit=key.rpm_limit,
            tpm_limit=key.tpm_limit,
            project_id=project.id if project else None,
            project_slug=project.slug if project else None,
            project_status=project.status if project else None,
            log_payloads=project.log_payloads if project else False,
            payload_retention_days=project.payload_retention_days if project else 0,
        )
        self._cache[prefix] = (entry, now + self._cache_ttl_s)
        return entry

    # ------------------------------------------------------------------- auth
    async def authenticate(self, raw_key: str | None) -> AuthContext:
        raw_key = (raw_key or "").strip()
        prefix = crypto.parse_key_prefix(raw_key)
        if prefix is None:
            raise AuthenticationError(_INVALID)

        entry = await self._lookup(prefix)
        if entry is None or not crypto.verify(raw_key, entry.key_hash):
            raise AuthenticationError(_INVALID)
        if entry.status != "active":
            raise AuthenticationError(_INVALID)
        if entry.expires_at is not None and entry.expires_at <= utcnow():
            raise AuthenticationError(_INVALID)
        if entry.project_id is not None and entry.project_status != "active":
            raise ProjectSuspended(
                f"Project '{entry.project_slug}' berstatus {entry.project_status}"
            )

        self._touch_last_used(entry)
        settings = get_settings()
        return AuthContext(
            key_id=entry.key_id,
            key_prefix=entry.key_prefix,
            role=entry.role,
            scopes=entry.scopes,
            project_id=entry.project_id,
            project_slug=entry.project_slug,
            log_payloads=entry.log_payloads,
            payload_retention_days=entry.payload_retention_days,
            rpm_limit=entry.rpm_limit or settings.default_rpm_limit,
            tpm_limit=entry.tpm_limit or settings.default_tpm_limit,
        )

    def _touch_last_used(self, entry: _CachedKey) -> None:
        """Update last_used_at maks 1x/menit per key, di background (tidak menunda request)."""
        now = time.monotonic()
        last = self._last_used.get(entry.key_prefix)
        if last is not None and now - last < LAST_USED_THROTTLE_S:
            return
        self._last_used[entry.key_prefix] = now
        task = asyncio.create_task(self._write_last_used(entry.key_id))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _write_last_used(self, key_id: uuid.UUID) -> None:
        try:
            async with self._session_factory() as session:
                await session.execute(
                    update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=utcnow())
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - jangan sampai mengganggu request
            log.warning("last_used_update_failed", key_id=str(key_id), error=str(exc))

    async def drain(self) -> None:
        """Tunggu background task selesai (dipakai saat shutdown & test)."""
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)

    # ------------------------------------------------------------ management
    @staticmethod
    def _validate(role: str, scopes: Iterable[str], project_id: uuid.UUID | None) -> list[str]:
        if role not in KEY_ROLES:
            raise InvalidRequestError(f"role tidak valid: {role}", param="role")
        scope_list = list(dict.fromkeys(scopes))
        unknown = sorted(set(scope_list) - set(VALID_SCOPES))
        if unknown:
            raise InvalidRequestError(f"scope tidak dikenal: {', '.join(unknown)}", param="scopes")
        if role == "client" and project_id is None:
            raise InvalidRequestError("key client wajib punya project", param="project_id")
        return scope_list

    async def create_key(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID | None,
        name: str,
        scopes: Iterable[str] = VALID_SCOPES,
        role: str = "client",
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        expires_at: datetime | None = None,
        created_by: uuid.UUID | None = None,
    ) -> tuple[str, ApiKey]:
        """Buat key baru. `full_key` dikembalikan sekali ini saja dan tidak disimpan."""
        scope_list = self._validate(role, scopes, project_id)
        full_key, prefix, key_hash = crypto.generate_api_key()
        key = ApiKey(
            project_id=project_id,
            name=name,
            role=role,
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=scope_list,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            expires_at=expires_at,
            created_by=created_by,
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)
        log.info("api_key_created", key_prefix=prefix, role=role, project_id=str(project_id))
        return full_key, key

    async def _get(self, session: AsyncSession, key_id: uuid.UUID) -> ApiKey:
        key = await session.get(ApiKey, key_id)
        if key is None:
            raise NotFound(f"API key {key_id} tidak ditemukan", param="key_id")
        return key

    async def revoke_key(
        self, session: AsyncSession, key_id: uuid.UUID, reason: str | None = None
    ) -> ApiKey:
        key = await self._get(session, key_id)
        if key.status != "revoked":
            key.status = "revoked"
            key.revoked_at = utcnow()
            key.revoked_reason = reason
            await session.commit()
        self.invalidate(key.key_prefix)
        log.info("api_key_revoked", key_prefix=key.key_prefix, reason=reason)
        return key

    async def rotate_key(
        self, session: AsyncSession, key_id: uuid.UUID, *, created_by: uuid.UUID | None = None
    ) -> tuple[str, ApiKey]:
        """Buat key baru dengan atribut sama, lalu revoke key lama."""
        old = await self._get(session, key_id)
        if old.status != "active":
            raise InvalidRequestError("Hanya key aktif yang dapat di-rotate", param="key_id")
        full_key, new = await self.create_key(
            session,
            project_id=old.project_id,
            name=old.name,
            scopes=old.scopes,
            role=old.role,
            rpm_limit=old.rpm_limit,
            tpm_limit=old.tpm_limit,
            expires_at=old.expires_at,
            created_by=created_by or old.created_by,
        )
        await self.revoke_key(session, old.id, reason=f"rotated -> {new.key_prefix}")
        return full_key, new


key_service = KeyService()
