"""Health & metrics gateway (TASK-18).

/health/ready:
- not_ready (503) bila DB gagal;
- degraded (200) bila ≥1 provider enabled gagal, runtime mati, device runtime tidak OK, atau ada
  model pinned belum termuat;
- ready selain itu.
Hasil provider di-cache 15 detik, dicek paralel dengan timeout 3 detik."""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from app.core.database import get_engine
from app.utils import metrics
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.registry import ProviderRegistry

log = get_logger(__name__)

PROVIDER_CACHE_S = 15.0
PROVIDER_TIMEOUT_S = 3.0
RUNTIME_METRICS_CACHE_S = 10.0


async def check_db() -> dict[str, Any]:
    from sqlalchemy import text

    start = time.perf_counter()
    try:
        async with get_engine().connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=PROVIDER_TIMEOUT_S)
        return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
    except Exception as exc:  # noqa: BLE001
        log.warning("db_ping_failed", error=str(exc))
        return {"ok": False, "detail": type(exc).__name__}


class HealthService:
    def __init__(self, clock: Any = time.monotonic) -> None:
        self.clock = clock
        self._providers: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._runtime_metrics: tuple[float, str] | None = None

    def invalidate(self) -> None:
        self._providers = None

    async def providers(self, registry: "ProviderRegistry") -> dict[str, dict[str, Any]]:
        if self._providers and self.clock() - self._providers[0] < PROVIDER_CACHE_S:
            return self._providers[1]
        codes = list(registry.providers)

        async def one(code: str) -> dict[str, Any]:
            try:
                health = await asyncio.wait_for(
                    registry.providers[code].health(), timeout=PROVIDER_TIMEOUT_S
                )
                return health.model_dump(exclude_none=True)
            except TimeoutError:
                return {"ok": False, "detail": f"timeout > {PROVIDER_TIMEOUT_S:g} s"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "detail": type(exc).__name__}

        results = await asyncio.gather(*(one(c) for c in codes))
        out = dict(zip(codes, results, strict=True))
        for code, reason in registry.disabled.items():
            out[code] = {"ok": None, "detail": reason}  # disabled: tidak memengaruhi status
        self._providers = (self.clock(), out)
        return out

    @staticmethod
    def runtime_section(registry: "ProviderRegistry", providers: dict[str, Any]) -> dict[str, Any]:
        local = [code for code, p in registry.providers.items() if hasattr(p, "runtime_request")]
        if not local:
            return {"ok": None, "detail": "runtime lokal tidak aktif"}
        info = providers.get(local[0]) or {}
        extra = info.get("extra") or {}
        memory = extra.get("memory") or {}
        devices = {
            d: {**(v if isinstance(v, dict) else {}), **(memory.get(d) or {})}
            for d, v in (extra.get("devices") or {}).items()
        }
        pinned = extra.get("pinned") or {}
        ok = (
            bool(info.get("ok"))
            and all(d.get("ok") for d in devices.values())
            and all(pinned.values())
        )
        section: dict[str, Any] = {"ok": ok, "devices": devices, "pinned_loaded": pinned}
        if extra.get("progress"):
            section["progress"] = extra["progress"]
        if not info.get("ok") and info.get("detail"):
            section["detail"] = info["detail"]
        return section

    async def ready(
        self, registry: "ProviderRegistry | None", *, privileged: bool
    ) -> tuple[int, dict[str, Any]]:
        db = await check_db()
        providers = await self.providers(registry) if registry is not None else {}
        runtime = self.runtime_section(registry, providers) if registry is not None else {}
        provider_ok = all(p.get("ok") is not False for p in providers.values())
        if not db["ok"]:
            status, http = "not_ready", 503
        elif not provider_ok or runtime.get("ok") is False:
            status, http = "degraded", 200
        else:
            status, http = "ready", 200
        public_providers = {
            code: (
                {k: v for k, v in p.items() if k != "extra"} if privileged else {"ok": p.get("ok")}
            )
            for code, p in providers.items()
        }
        if not privileged:
            runtime = {k: v for k, v in runtime.items() if k != "detail"}
            db = {k: v for k, v in db.items() if k != "detail"}
        return http, {
            "status": status,
            "database": db,
            "providers": public_providers,
            "runtime": runtime,
        }

    async def metrics_text(self, registry: "ProviderRegistry | None") -> bytes:
        """Metrik gateway + metrik runtime (fetch ber-cache 10 detik) dalam satu endpoint."""
        body = metrics.render()
        text = ""
        if (
            self._runtime_metrics
            and self.clock() - self._runtime_metrics[0] < RUNTIME_METRICS_CACHE_S
        ):
            text = self._runtime_metrics[1]
        elif registry is not None:
            for provider in registry.providers.values():
                fetch = getattr(provider, "metrics_text", None)
                if fetch is None:
                    continue
                try:
                    text = await fetch()
                except Exception as exc:  # noqa: BLE001 - runtime mati: metrik gateway tetap ada
                    log.warning("runtime_metrics_unavailable", error=str(exc))
                    text = ""
                self._runtime_metrics = (self.clock(), text)
                break
        return body + text.encode() if text else body


health_service = HealthService()
