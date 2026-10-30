import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psutil

from app.core.config import Settings
from app.utils.logger import get_logger
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog
from runtime.device.manager import DeviceManager
from runtime.device.probe import DeviceProbe
from runtime.services.event_service import EventService
from runtime.services.inference_service import InferenceService

log = get_logger("runtime.state")

# Cadangan di atas ukuran model GPU terbesar agar load tidak menghabiskan RAM (UMA: memori iGPU =
# RAM sistem). Di bawah ini load 7B terukur gagal di driver ("[GPU] ProgramBuilder build failed",
# CL_INVALID_EVENT) saat RAM bebas turun ke 0 (TASK-20).
RAM_HEADROOM_MB = 1024


def available_ram_mb() -> int:
    return int(psutil.virtual_memory().available // (1024 * 1024))


@dataclass
class RuntimeState:
    settings: Settings
    events: EventService
    catalog: RuntimeCatalog
    managers: dict[str, DeviceManager]
    service: InferenceService
    probe: DeviceProbe
    started_at: float = field(default_factory=time.monotonic)
    warmup_task: asyncio.Task[None] | None = None
    warmup_errors: dict[str, str] = field(default_factory=dict)
    shutting_down: bool = False
    free_ram_mb: Callable[[], int] = available_ram_mb

    def pinned_specs(self) -> list[LocalModelSpec]:
        return [s for s in self.catalog.specs.values() if s.is_pinned and s.device in self.managers]

    def ram_headroom(self) -> dict[str, Any]:
        """RAM sistem bebas vs kebutuhan model GPU (non-pinned) terbesar yang belum termuat.
        `low` = load model itu kemungkinan gagal / sangat lambat karena RAM habis."""
        gpu = self.managers.get("gpu")
        candidates = [
            s.vram_mb
            for s in self.catalog.specs.values()
            if s.device == "gpu" and not (gpu and gpu.is_loaded(s.alias))
        ]
        need = max(candidates, default=0)
        free = self.free_ram_mb()
        return {
            "system_available_mb": free,
            "largest_gpu_load_mb": need,
            "low": bool(need) and free < need + RAM_HEADROOM_MB,
        }

    def pinned_status(self) -> dict[str, bool]:
        return {s.alias: self.managers[s.device].is_loaded(s.alias) for s in self.pinned_specs()}

    @property
    def ready(self) -> bool:
        return not self.shutting_down and all(self.pinned_status().values())

    async def warmup(self) -> None:
        """Muat model pinned (berurutan per device). Gagal → dicatat, runtime tetap hidup."""
        for spec in self.pinned_specs():
            try:
                await self.managers[spec.device].load(spec, reason="warmup")
                self.warmup_errors.pop(spec.alias, None)
            except Exception as exc:  # noqa: BLE001
                self.warmup_errors[spec.alias] = str(exc)
                log.error("warmup_failed", model=spec.alias, error=str(exc))
        headroom = self.ram_headroom()
        if headroom["low"]:
            log.warning(
                "low_system_ram",
                message="RAM bebas tidak cukup untuk memuat model GPU terbesar; tutup aplikasi "
                "lain atau kurangi model pinned (lihat docs/perf-report.md)",
                **headroom,
            )

    def start_warmup(self) -> None:
        if self.warmup_task is None or self.warmup_task.done():
            self.warmup_task = asyncio.ensure_future(self.warmup())

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "uptime_s": round(time.monotonic() - self.started_at, 1),
            "allow_cpu_fallback": self.settings.allow_cpu_fallback,
            "devices": {
                d: {
                    **vars(m.status()),
                    "available": self.probe.available(d),
                    "name": getattr(self.probe, d).name,
                }
                for d, m in self.managers.items()
            },
            "pinned": self.pinned_status(),
            "warmup_errors": self.warmup_errors,
            "catalog": sorted(self.catalog.specs),
        }
