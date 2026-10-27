import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.core.config import Settings
from app.core.database import dispose_db, init_db
from app.utils.logger import get_logger, setup_logging, shutdown_logging
from runtime.backends import create_backend
from runtime.backends.base import LocalBackend
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog
from runtime.core.settings import device_budgets
from runtime.core.state import RuntimeState
from runtime.device import probe as probe_mod
from runtime.device.manager import DeviceManager
from runtime.device.probe import DeviceProbe
from runtime.services.event_service import EventService
from runtime.services.inference_service import InferenceService

log = get_logger("runtime")


class RuntimeStartError(RuntimeError):
    pass


def build_state(
    settings: Settings,
    probe: DeviceProbe,
    catalog: RuntimeCatalog,
    events: EventService,
    backend_factory: Callable[[LocalModelSpec], LocalBackend] = create_backend,
) -> RuntimeState:
    budgets = device_budgets(settings)
    managers = {}
    for device, budget in budgets.items():
        replicas = sum(s.replicas for s in catalog.specs.values() if s.device == device)
        managers[device] = DeviceManager(
            device,
            budget,
            min_residency_s=settings.runtime_min_residency_s,
            queue_timeout_s=settings.runtime_queue_timeout_s,
            allow_cpu_fallback=settings.allow_cpu_fallback,
            backend_factory=backend_factory,
            events=events,
            max_workers=max(1, replicas),
        )
    return RuntimeState(
        settings=settings,
        events=events,
        catalog=catalog,
        managers=managers,
        service=InferenceService(catalog, managers),
        probe=probe,
    )


def check_devices(
    settings: Settings, probe: DeviceProbe, catalog: RuntimeCatalog, events: EventService
) -> None:
    """Gagal start bila device yang dibutuhkan model enabled tidak ada (kecuali CPU fallback)."""
    needed = sorted({s.device for s in catalog.specs.values()})
    missing = [d for d in needed if not probe.available(d)]
    if not missing:
        return
    for device in missing:
        events.record(
            "device_error",
            device=device if device in ("gpu", "npu") else "cpu",
            reason=f"{device} tidak terdeteksi",
            details={"errors": probe.errors},
        )
    message = (
        f"Device {', '.join(missing).upper()} tidak terdeteksi, padahal dibutuhkan model enabled "
        f"({', '.join(s.alias for s in catalog.specs.values() if s.device in missing)}). "
        f"Detail probe: {probe.errors or '-'}"
    )
    if settings.allow_cpu_fallback:
        log.warning("device_missing_cpu_fallback", message=message)
        return
    raise RuntimeStartError(message + " Set ALLOW_CPU_FALLBACK=true hanya untuk dev/debug.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    setup_logging(settings, component="runtime")
    log.info("runtime_starting", budgets=device_budgets(settings))
    await init_db(settings)

    events = EventService(Path(settings.log_dir) / "runtime_events_fallback.jsonl")
    catalog = RuntimeCatalog()
    try:
        await catalog.load()
    except Exception as exc:
        await dispose_db()
        shutdown_logging()
        raise RuntimeStartError(f"Gagal membaca katalog model dari DB: {exc}") from exc

    probe = await asyncio.to_thread(probe_mod.detect)
    log.info(
        "device_probe",
        gpu=probe.gpu.available,
        npu=probe.npu.available,
        gpu_name=probe.gpu.name,
        npu_name=probe.npu.name,
    )
    try:
        check_devices(settings, probe, catalog, events)
    except RuntimeStartError:
        await events.drain()
        await dispose_db()
        shutdown_logging()
        raise

    state = build_state(settings, probe, catalog, events)
    app.state.rt = state
    events.record(
        "runtime_start",
        device="gpu" if probe.gpu.available else "npu",
        details={
            "probe": {"gpu": probe.gpu.available, "npu": probe.npu.available},
            "models": sorted(catalog.specs),
        },
    )
    state.start_warmup()
    try:
        yield
    finally:
        state.shutting_down = True
        if state.warmup_task is not None:
            state.warmup_task.cancel()
            with contextlib.suppress(BaseException):
                await state.warmup_task
        for manager in state.managers.values():
            await manager.unload_all("runtime_stop")
            manager.close()
        events.record("runtime_stop", device="gpu" if probe.gpu.available else "npu")
        await events.drain()
        await dispose_db()
        log.info("runtime_stopped")
        shutdown_logging()
