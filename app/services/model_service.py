"""Admin: provider, model, route (TASK-17). Perubahan berlaku tanpa restart: setelah commit
registry gateway di-reload dan (untuk model lokal) katalog runtime di-reload."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import Model, ModelRoute, ModelRouteTarget, Provider
from app.schemas.admin import (
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ProviderOut,
    ProviderUpdate,
    RouteCreate,
    RouteOut,
    RouteUpdate,
    snapshot,
)
from app.services import audit_service
from app.services.audit_service import Actor
from app.services.project_service import check_if_match
from app.utils.errors import Conflict, InvalidRequestError, NotFound, Unprocessable
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.registry import ProviderRegistry

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------- helpers
def model_out(model: Model, provider_code: str) -> dict[str, Any]:
    data = {c: getattr(model, c) for c in ModelOut.model_fields if c != "provider_code"}
    return ModelOut.model_validate({**data, "provider_code": provider_code}).model_dump(mode="json")


def route_out(route: ModelRoute) -> dict[str, Any]:
    targets = sorted(
        (
            {"model_alias": t.model.alias, "priority": t.priority, "weight": t.weight}
            for t in route.targets
        ),
        key=lambda t: (t["priority"], t["model_alias"]),
    )
    data = {c: getattr(route, c) for c in RouteOut.model_fields if c != "targets"}
    return RouteOut.model_validate({**data, "targets": targets}).model_dump(mode="json")


async def _provider_codes(session: AsyncSession) -> dict[Any, str]:
    return dict((await session.execute(select(Provider.id, Provider.code))).all())


async def _model(session: AsyncSession, alias: str) -> Model:
    model = (await session.execute(select(Model).where(Model.alias == alias))).scalar_one_or_none()
    if model is None:
        raise NotFound(f"Model '{alias}' tidak ditemukan", param="alias")
    return model


async def _route(session: AsyncSession, alias: str) -> ModelRoute:
    route = (
        await session.execute(
            select(ModelRoute)
            .where(ModelRoute.alias == alias)
            .options(selectinload(ModelRoute.targets).selectinload(ModelRouteTarget.model))
        )
    ).scalar_one_or_none()
    if route is None:
        raise NotFound(f"Route '{alias}' tidak ditemukan", param="alias")
    return route


async def reload_everything(registry: "ProviderRegistry | None", *, runtime: bool) -> list[str]:
    """Reload registry gateway (+ katalog runtime). Kegagalan runtime → peringatan, bukan error
    (data sudah tersimpan; runtime membaca ulang saat start berikutnya)."""
    warnings: list[str] = []
    if registry is not None:
        await registry.reload()
    if runtime and registry is not None:
        provider = local_provider(registry)
        if provider is None:
            warnings.append("runtime_provider_inactive")
        else:
            try:
                status, _ = await provider.runtime_request("POST", "/runtime/catalog/reload")
                if status != 200:
                    warnings.append(f"runtime_catalog_reload_http_{status}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"runtime_unreachable:{type(exc).__name__}")
    return warnings


def local_provider(registry: "ProviderRegistry") -> Any:
    for provider in registry.providers.values():
        if hasattr(provider, "runtime_request"):
            return provider
    return None


async def _validate_local(session: AsyncSession, model: Model) -> None:
    """Aturan model lokal: backend wajib, tanpa CPU, artefak ada, total pinned ≤ budget device."""
    if model.device == "remote":
        return
    settings = get_settings()
    if model.device == "cpu" and not settings.allow_cpu_fallback:
        raise Unprocessable(
            "device lokal 'cpu' dilarang (ALLOW_CPU_FALLBACK=false)", param="device"
        )
    if not model.runtime_backend:
        raise Unprocessable("model lokal wajib runtime_backend", param="runtime_backend")
    if model.artifact_path:
        path = Path(model.artifact_path)
        if not (path if path.is_absolute() else ROOT / path).exists():
            raise Unprocessable(
                f"artifact_path tidak ada di disk: {model.artifact_path}", param="artifact_path"
            )
    budgets = {"gpu": settings.gpu_budget_mb, "npu": settings.npu_budget_mb}
    budget = budgets.get(model.device)
    if budget is None or not (model.is_pinned and model.is_enabled):
        return
    others = (
        await session.execute(
            select(Model.alias, Model.vram_mb).where(
                Model.device == model.device,
                Model.is_pinned.is_(True),
                Model.is_enabled.is_(True),
                Model.id != model.id,
            )
        )
    ).all()
    total = sum(v or 0 for _, v in others) + (model.vram_mb or 0)
    if total > budget:
        detail = ", ".join(f"{a}={v or 0}" for a, v in others)
        raise Unprocessable(
            f"Total vram_mb model pinned di {model.device.upper()} {total} MB > budget "
            f"{budget} MB ({detail}{', ' if detail else ''}{model.alias}={model.vram_mb or 0})",
            param="is_pinned",
        )


# ----------------------------------------------------------------- providers
async def list_providers(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Provider).order_by(Provider.code))).scalars().all()
    return [snapshot(ProviderOut, p) for p in rows]


async def update_provider(
    session: AsyncSession,
    actor: Actor,
    code: str,
    body: ProviderUpdate,
    registry: "ProviderRegistry | None",
    if_match: str | None = None,
) -> dict[str, Any]:
    provider = (
        await session.execute(select(Provider).where(Provider.code == code))
    ).scalar_one_or_none()
    if provider is None:
        raise NotFound(f"Provider '{code}' tidak ditemukan", param="code")
    check_if_match(provider.updated_at, if_match)
    before = snapshot(ProviderOut, provider)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
    await session.flush()
    await session.refresh(provider)
    after = snapshot(ProviderOut, provider)
    audit_service.record(session, actor, "provider.update", "provider", code, before, after)
    await session.commit()
    await reload_everything(registry, runtime=False)
    return after


async def test_provider(code: str, registry: "ProviderRegistry") -> dict[str, Any]:
    provider = registry.get(code)
    if provider is None:
        return {"ok": False, "detail": registry.disabled.get(code, "provider tidak terdaftar")}
    health = await provider.health()
    return health.model_dump(exclude_none=True)


# -------------------------------------------------------------------- models
async def list_models(session: AsyncSession) -> list[dict[str, Any]]:
    codes = await _provider_codes(session)
    rows = (await session.execute(select(Model).order_by(Model.alias))).scalars().all()
    return [model_out(m, codes[m.provider_id]) for m in rows]


async def create_model(
    session: AsyncSession, actor: Actor, body: ModelCreate, registry: "ProviderRegistry | None"
) -> dict[str, Any]:
    provider = (
        await session.execute(select(Provider).where(Provider.code == body.provider))
    ).scalar_one_or_none()
    if provider is None:
        raise InvalidRequestError(f"Provider '{body.provider}' tidak ada", param="provider")
    if (await session.execute(select(ModelRoute.id).where(ModelRoute.alias == body.alias))).first():
        raise Conflict(f"Alias '{body.alias}' sudah dipakai route", param="alias")
    if (await session.execute(select(Model.id).where(Model.alias == body.alias))).first():
        raise Conflict(f"Model '{body.alias}' sudah ada", param="alias")
    values = body.model_dump(exclude_unset=True, exclude={"provider"})
    model = Model(provider_id=provider.id, **values)
    session.add(model)
    await session.flush()
    await session.refresh(model)
    await _validate_local(session, model)
    after = model_out(model, provider.code)
    audit_service.record(session, actor, "model.create", "model", model.alias, None, after)
    await session.commit()
    warnings = await reload_everything(registry, runtime=model.device != "remote")
    return {**after, "warnings": warnings}


async def update_model(
    session: AsyncSession,
    actor: Actor,
    alias: str,
    body: ModelUpdate,
    registry: "ProviderRegistry | None",
    if_match: str | None = None,
) -> dict[str, Any]:
    model = await _model(session, alias)
    check_if_match(model.updated_at, if_match)
    codes = await _provider_codes(session)
    before = model_out(model, codes[model.provider_id])
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(model, field, value)
    await session.flush()
    await session.refresh(model)
    await _validate_local(session, model)
    after = model_out(model, codes[model.provider_id])
    action = "model.update"
    if set(changes) == {"is_pinned"} and before["is_pinned"] != after["is_pinned"]:
        action = "model.pin" if after["is_pinned"] else "model.unpin"
    audit_service.record(session, actor, action, "model", alias, before, after)
    await session.commit()
    local = model.device != "remote" or before["device"] != "remote"
    warnings = await reload_everything(registry, runtime=local)
    return {**after, "warnings": warnings}


async def delete_model(
    session: AsyncSession, actor: Actor, alias: str, registry: "ProviderRegistry | None"
) -> dict[str, Any]:
    model = await _model(session, alias)
    routes = (
        (
            await session.execute(
                select(ModelRoute.alias)
                .join(ModelRouteTarget, ModelRouteTarget.route_id == ModelRoute.id)
                .where(ModelRouteTarget.model_id == model.id)
            )
        )
        .scalars()
        .all()
    )
    if routes:
        raise Conflict(
            f"Model '{alias}' masih dipakai route {sorted(routes)}; hapus dari route atau "
            "nonaktifkan model (PATCH is_enabled=false)"
        )
    codes = await _provider_codes(session)
    before = model_out(model, codes[model.provider_id])
    local = model.device != "remote"
    await session.delete(model)
    audit_service.record(session, actor, "model.delete", "model", alias, before, None)
    await session.commit()
    await reload_everything(registry, runtime=local)
    return {"deleted": alias}


# -------------------------------------------------------------------- routes
async def list_routes(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(ModelRoute)
                .options(selectinload(ModelRoute.targets).selectinload(ModelRouteTarget.model))
                .order_by(ModelRoute.alias)
            )
        )
        .scalars()
        .all()
    )
    return [route_out(r) for r in rows]


async def _set_targets(session: AsyncSession, route: ModelRoute, targets: list[Any]) -> None:
    aliases = [t.model_alias for t in targets]
    if len(set(aliases)) != len(aliases):
        raise InvalidRequestError("target route duplikat", param="targets")
    models = {
        m.alias: m
        for m in (await session.execute(select(Model).where(Model.alias.in_(aliases)))).scalars()
    }
    missing = [a for a in aliases if a not in models]
    if missing:
        raise InvalidRequestError(f"model target tidak ada: {missing}", param="targets")
    if not any(models[a].is_enabled for a in aliases):
        raise Unprocessable(
            "route wajib punya minimal 1 target model yang enabled", param="targets"
        )
    await session.execute(delete(ModelRouteTarget).where(ModelRouteTarget.route_id == route.id))
    session.add_all(
        ModelRouteTarget(
            route_id=route.id,
            model_id=models[t.model_alias].id,
            priority=t.priority,
            weight=t.weight,
        )
        for t in targets
    )
    await session.flush()


async def create_route(
    session: AsyncSession, actor: Actor, body: RouteCreate, registry: "ProviderRegistry | None"
) -> dict[str, Any]:
    if (await session.execute(select(Model.id).where(Model.alias == body.alias))).first():
        raise Conflict(f"Alias '{body.alias}' sudah dipakai model", param="alias")
    if (await session.execute(select(ModelRoute.id).where(ModelRoute.alias == body.alias))).first():
        raise Conflict(f"Route '{body.alias}' sudah ada", param="alias")
    route = ModelRoute(**body.model_dump(exclude={"targets"}))
    session.add(route)
    await session.flush()
    await _set_targets(session, route, body.targets)
    session.expire(route)
    after = route_out(await _route(session, body.alias))
    audit_service.record(session, actor, "route.create", "route", body.alias, None, after)
    await session.commit()
    await reload_everything(registry, runtime=False)
    return after


async def update_route(
    session: AsyncSession,
    actor: Actor,
    alias: str,
    body: RouteUpdate,
    registry: "ProviderRegistry | None",
    if_match: str | None = None,
) -> dict[str, Any]:
    route = await _route(session, alias)
    check_if_match(route.updated_at, if_match)
    before = route_out(route)
    changes = body.model_dump(exclude_unset=True, exclude={"targets"})
    for field, value in changes.items():
        setattr(route, field, value)
    if body.targets is not None:
        await _set_targets(session, route, body.targets)
        route.updated_at = func.now()  # perubahan target juga mengubah versi route (If-Match)
    await session.flush()
    session.expire(route)
    after = route_out(await _route(session, alias))
    audit_service.record(session, actor, "route.update", "route", alias, before, after)
    await session.commit()
    await reload_everything(registry, runtime=False)
    return after


async def delete_route(
    session: AsyncSession, actor: Actor, alias: str, registry: "ProviderRegistry | None"
) -> dict[str, Any]:
    route = await _route(session, alias)
    before = route_out(route)
    await session.delete(route)
    audit_service.record(session, actor, "route.delete", "route", alias, before, None)
    await session.commit()
    await reload_everything(registry, runtime=False)
    return {"deleted": alias}
