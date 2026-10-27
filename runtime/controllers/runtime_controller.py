import asyncio
import signal
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.utils.logger import get_logger
from runtime.core.state import RuntimeState

log = get_logger("runtime.admin")


def _state(request: Request) -> RuntimeState:
    return request.app.state.rt  # type: ignore[no-any-return]


async def status(request: Request) -> dict[str, Any]:
    return _state(request).status()


async def load_model(request: Request, name: str, pin: bool = False) -> dict[str, Any]:
    state = _state(request)
    spec, manager = state.service.resolve(name)
    load_ms = await manager.load(spec, reason="manual", pin=pin)
    return {
        "model": spec.alias,
        "loaded": True,
        "load_ms": load_ms,
        "pinned": pin or spec.is_pinned,
    }


async def unload_model(request: Request, name: str, force: bool = False) -> dict[str, Any]:
    state = _state(request)
    spec, manager = state.service.resolve(name)
    unloaded = await manager.unload(spec.alias, reason="manual", force=force)
    return {"model": spec.alias, "unloaded": unloaded}


async def reload_catalog(request: Request) -> dict[str, Any]:
    """Baca ulang tabel models. Model termuat yang dihapus/disabled di-unload; model pinned baru
    di-warmup."""
    state = _state(request)
    old = dict(state.catalog.specs)
    specs = await state.catalog.load()
    removed = {s.alias for s in old.values()} - {s.alias for s in specs.values()}
    for spec in old.values():
        if spec.alias in removed and spec.device in state.managers:
            await state.managers[spec.device].unload(
                spec.alias, reason="catalog_reload", force=True
            )
    for spec in specs.values():
        if spec.device in state.managers:
            state.managers[spec.device].set_pinned(spec.alias, spec.is_pinned)
    state.start_warmup()
    return {"models": sorted(specs), "removed": sorted(removed)}


async def shutdown(request: Request) -> dict[str, Any]:
    """Unload semua (via lifespan shutdown) lalu keluar dengan kode 0 (supervisor tidak restart)."""
    state = _state(request)
    state.shutting_down = True
    log.info("runtime_shutdown_requested")

    async def _stop() -> None:
        await asyncio.sleep(0.2)  # biarkan respons terkirim dulu
        signal.raise_signal(signal.SIGINT)

    asyncio.get_running_loop().create_task(_stop())
    return {"status": "shutting_down"}


async def health_ready(request: Request) -> JSONResponse:
    state: RuntimeState | None = getattr(request.app.state, "rt", None)
    if state is None:
        return JSONResponse({"ready": False, "status": "starting"}, status_code=503)
    body = {
        "ready": state.ready,
        "status": "ok" if state.ready else "warming_up",
        "devices": {
            "gpu": {"ok": state.probe.gpu.available, "name": state.probe.gpu.name},
            "npu": {"ok": state.probe.npu.available, "name": state.probe.npu.name},
        },
        "pinned": state.pinned_status(),
        "warmup_errors": state.warmup_errors,
    }
    return JSONResponse(body, status_code=200 if state.ready else 503)
