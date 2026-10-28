"""Admin: project, pola model diizinkan, API key, kuota (TASK-17). Setiap operasi tulis = satu
transaksi berisi perubahan + tepat satu baris audit."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, Project, Quota
from app.models.api_key import VALID_SCOPES
from app.models.project import ProjectAllowedModel
from app.schemas.admin import (
    AllowedModelsSet,
    ApiKeyCreatedOut,
    ApiKeyOut,
    KeyCreate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    QuotaOut,
    QuotasSet,
    snapshot,
)
from app.services import audit_service
from app.services.audit_service import Actor
from app.services.key_service import key_service
from app.services.quota_service import quota_service
from app.utils.errors import Conflict, InvalidRequestError, NotFound


def check_if_match(updated_at: datetime, if_match: str | None) -> None:
    """Concurrency edit opsional: header If-Match = updated_at ISO terakhir yang dilihat klien."""
    if not if_match:
        return
    try:
        expected = datetime.fromisoformat(if_match.strip().strip('"'))
    except ValueError as exc:
        raise InvalidRequestError("If-Match harus timestamp ISO 8601 (updated_at)") from exc
    if expected != updated_at:
        raise Conflict(
            f"Data sudah berubah (updated_at sekarang {updated_at.isoformat()}); muat ulang"
        )


async def _project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"Project {project_id} tidak ditemukan", param="project_id")
    return project


async def _patterns(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(ProjectAllowedModel.model_pattern)
                .where(ProjectAllowedModel.project_id == project_id)
                .order_by(ProjectAllowedModel.model_pattern)
            )
        )
        .scalars()
        .all()
    )


async def _invalidate_project_keys(session: AsyncSession, project_id: uuid.UUID) -> None:
    prefixes = (
        await session.execute(select(ApiKey.key_prefix).where(ApiKey.project_id == project_id))
    ).scalars()
    for prefix in prefixes:
        key_service.invalidate(prefix)


# ------------------------------------------------------------------ projects
async def list_projects(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Project).order_by(Project.slug))).scalars().all()
    return [snapshot(ProjectOut, p) for p in rows]


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    project = await _project(session, project_id)
    return {
        **snapshot(ProjectOut, project),
        "allowed_models": await _patterns(session, project_id),
    }


async def create_project(
    session: AsyncSession, actor: Actor, body: ProjectCreate
) -> dict[str, Any]:
    data = body.model_dump(exclude={"allowed_models"})
    project = Project(**data)
    session.add(project)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(f"slug '{body.slug}' sudah dipakai", param="slug") from exc
    patterns = list(dict.fromkeys(p.strip() for p in body.allowed_models if p.strip()))
    session.add_all(ProjectAllowedModel(project_id=project.id, model_pattern=p) for p in patterns)
    await session.refresh(project)
    after = {**snapshot(ProjectOut, project), "allowed_models": patterns}
    audit_service.record(session, actor, "project.create", "project", project.id, None, after)
    await session.commit()
    return after


async def update_project(
    session: AsyncSession,
    actor: Actor,
    project_id: uuid.UUID,
    body: ProjectUpdate,
    if_match: str | None = None,
) -> dict[str, Any]:
    project = await _project(session, project_id)
    check_if_match(project.updated_at, if_match)
    if project.status == "archived":
        raise Conflict("Project sudah diarsipkan")
    before = snapshot(ProjectOut, project)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.flush()
    await session.refresh(project)
    after = snapshot(ProjectOut, project)
    audit_service.record(session, actor, "project.update", "project", project.id, before, after)
    await session.commit()
    # status/flag payload ikut di cache auth → invalidate semua key project
    await _invalidate_project_keys(session, project_id)
    return after


async def archive_project(
    session: AsyncSession, actor: Actor, project_id: uuid.UUID
) -> dict[str, Any]:
    project = await _project(session, project_id)
    before = snapshot(ProjectOut, project)
    project.status = "archived"
    keys = (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.project_id == project_id, ApiKey.status == "active")
            )
        )
        .scalars()
        .all()
    )
    for key in keys:
        await key_service.revoke_key(session, key.id, reason="project archived", commit=False)
    await session.flush()
    await session.refresh(project)
    after = {**snapshot(ProjectOut, project), "revoked_keys": [k.key_prefix for k in keys]}
    audit_service.record(session, actor, "project.archive", "project", project.id, before, after)
    await session.commit()
    await _invalidate_project_keys(session, project_id)
    return after


async def set_allowed_models(
    session: AsyncSession, actor: Actor, project_id: uuid.UUID, body: AllowedModelsSet
) -> dict[str, Any]:
    await _project(session, project_id)
    before = {"patterns": await _patterns(session, project_id)}
    await session.execute(
        delete(ProjectAllowedModel).where(ProjectAllowedModel.project_id == project_id)
    )
    session.add_all(
        ProjectAllowedModel(project_id=project_id, model_pattern=p) for p in body.patterns
    )
    after = {"patterns": sorted(body.patterns)}
    audit_service.record(
        session, actor, "project.allowed_models.set", "project", project_id, before, after
    )
    await session.commit()
    await _invalidate_project_keys(session, project_id)
    return after


# ---------------------------------------------------------------------- keys
async def list_keys(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    await _project(session, project_id)
    rows = (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.project_id == project_id).order_by(ApiKey.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [snapshot(ApiKeyOut, k) for k in rows]


async def create_key(
    session: AsyncSession, actor: Actor, project_id: uuid.UUID, body: KeyCreate
) -> dict[str, Any]:
    project = await _project(session, project_id)
    if project.status != "active":
        raise Conflict(f"Project berstatus {project.status}")
    full_key, key = await key_service.create_key(
        session,
        project_id=project_id,
        name=body.name,
        scopes=body.scopes if body.scopes is not None else VALID_SCOPES,
        role="client",
        rpm_limit=body.rpm_limit,
        tpm_limit=body.tpm_limit,
        expires_at=body.expires_at,
        created_by=actor.auth.key_id if actor.auth else None,
        commit=False,
    )
    after = snapshot(ApiKeyOut, key)
    audit_service.record(session, actor, "key.create", "api_key", key.id, None, after)
    await session.commit()
    return {**after, "key": full_key}


async def _key(session: AsyncSession, key_id: uuid.UUID) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFound(f"API key {key_id} tidak ditemukan", param="key_id")
    return key


async def revoke_key(
    session: AsyncSession, actor: Actor, key_id: uuid.UUID, reason: str
) -> dict[str, Any]:
    key = await _key(session, key_id)
    before = snapshot(ApiKeyOut, key)
    await key_service.revoke_key(session, key_id, reason=reason, commit=False)
    await session.refresh(key)
    after = snapshot(ApiKeyOut, key)
    audit_service.record(session, actor, "key.revoke", "api_key", key_id, before, after)
    await session.commit()
    key_service.invalidate(key.key_prefix)
    return after


async def rotate_key(session: AsyncSession, actor: Actor, key_id: uuid.UUID) -> dict[str, Any]:
    old = await _key(session, key_id)
    before = snapshot(ApiKeyOut, old)
    full_key, new = await key_service.rotate_key(
        session, key_id, created_by=actor.auth.key_id if actor.auth else None, commit=False
    )
    after = snapshot(ApiKeyOut, new)
    audit_service.record(
        session, actor, "key.rotate", "api_key", key_id, before, {"new_key": after}
    )
    await session.commit()
    key_service.invalidate(old.key_prefix)
    return ApiKeyCreatedOut.model_validate({**after, "key": full_key}).model_dump(mode="json")


# -------------------------------------------------------------------- quotas
async def list_quotas(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    await _project(session, project_id)
    rows = (
        (await session.execute(select(Quota).where(Quota.project_id == project_id))).scalars().all()
    )
    return [snapshot(QuotaOut, q) for q in rows]


async def set_quotas(
    session: AsyncSession, actor: Actor, project_id: uuid.UUID, body: QuotasSet
) -> list[dict[str, Any]]:
    await _project(session, project_id)
    if len({q.period for q in body.quotas}) != len(body.quotas):
        raise InvalidRequestError("period tidak boleh duplikat", param="quotas")
    existing = {
        q.period: q
        for q in (
            await session.execute(select(Quota).where(Quota.project_id == project_id))
        ).scalars()
    }
    before = [snapshot(QuotaOut, q) for q in existing.values()]
    for item in body.quotas:
        row = existing.get(item.period)
        if row is None:
            row = Quota(project_id=project_id, period=item.period)
            session.add(row)
        for field, value in item.model_dump(exclude={"period"}).items():
            setattr(row, field, value)
    await session.flush()
    after = await list_quotas(session, project_id)
    audit_service.record(
        session, actor, "quota.set", "project", project_id, {"quotas": before}, {"quotas": after}
    )
    await session.commit()
    quota_service.invalidate(project_id)
    return after
