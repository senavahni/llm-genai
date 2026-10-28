"""Admin → Local Runtime (TASK-17): status, load/unload manual dengan audit, reload cache."""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import audit_service
from app.services.audit_service import Actor
from app.services.key_service import key_service
from app.services.model_service import local_provider, reload_everything
from app.services.quota_service import quota_service
from app.utils.errors import Conflict, GatewayError, ServiceUnavailable

if TYPE_CHECKING:
    from app.core.registry import ProviderRegistry

FORCE_UNLOAD_WAIT_S = 60.0


def _provider(registry: "ProviderRegistry") -> Any:
    provider = local_provider(registry)
    if provider is None:
        raise ServiceUnavailable("Provider runtime lokal tidak aktif")
    return provider


async def _call(registry: "ProviderRegistry", method: str, path: str, **kw: Any) -> dict[str, Any]:
    provider = _provider(registry)
    try:
        status, body = await provider.runtime_request(method, path, **kw)
    except Exception as exc:  # noqa: BLE001
        raise ServiceUnavailable(f"Runtime tidak terjangkau: {type(exc).__name__}") from exc
    if status >= 400:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        mapped = provider.map_runtime_error(status, body)
        if isinstance(mapped, GatewayError):
            raise mapped
        raise ServiceUnavailable(f"Runtime HTTP {status}: {err.get('message') or body}")
    return body


async def status(registry: "ProviderRegistry") -> dict[str, Any]:
    return await _call(registry, "GET", "/runtime/status")


def _model_entry(state: dict[str, Any], alias: str) -> dict[str, Any] | None:
    for device in (state.get("devices") or {}).values():
        for model in device.get("models") or []:
            if model.get("alias") == alias:
                return model  # type: ignore[no-any-return]
    return None


async def load(
    session: AsyncSession, actor: Actor, registry: "ProviderRegistry", alias: str, pin: bool
) -> dict[str, Any]:
    result = await _call(
        registry,
        "POST",
        f"/runtime/models/{alias}/load",
        params={"pin": str(pin).lower()},
        timeout=900.0,  # compile NPU pertama bisa beberapa menit
    )
    audit_service.record(session, actor, "runtime.load", "model", alias, None, result)
    await session.commit()
    return result


async def unload(
    session: AsyncSession, actor: Actor, registry: "ProviderRegistry", alias: str, force: bool
) -> dict[str, Any]:
    entry = _model_entry(await status(registry), alias)
    if entry is None:
        return {"model": alias, "unloaded": False, "detail": "tidak termuat"}
    if not force and (entry.get("pinned") or entry.get("in_flight", 0) > 0):
        why = "pinned" if entry.get("pinned") else f"in_flight={entry.get('in_flight')}"
        raise Conflict(f"Model {alias} {why}; pakai ?force=true untuk memaksa")
    if force:
        # tunggu request berjalan selesai (maks 60 detik) sebelum unload paksa
        deadline = time.monotonic() + FORCE_UNLOAD_WAIT_S
        while (entry or {}).get("in_flight", 0) > 0 and time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            entry = _model_entry(await status(registry), alias)
    result = await _call(
        registry, "POST", f"/runtime/models/{alias}/unload", params={"force": str(force).lower()}
    )
    audit_service.record(
        session, actor, "runtime.unload", "model", alias, entry, {**result, "force": force}
    )
    await session.commit()
    return result


async def reload_caches(
    session: AsyncSession, actor: Actor, registry: "ProviderRegistry | None"
) -> dict[str, Any]:
    warnings = await reload_everything(registry, runtime=True)
    key_service.invalidate()
    quota_service.invalidate()
    after = {"registry": "reloaded", "warnings": warnings}
    audit_service.record(session, actor, "cache.reload", "system", None, None, after)
    await session.commit()
    return after
