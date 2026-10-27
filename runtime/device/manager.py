"""Device/VRAM Manager (PRD §7.5): budget per device, model pinned, eviction LRU dengan minimum
residency, satu proses load per device, antrean per model, penanganan OOM, larangan CPU."""

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.utils.errors import (
    DeviceOOM,
    DeviceUnavailable,
    GatewayError,
    ModelBusy,
    ModelLoadFailed,
)
from app.utils.logger import get_logger
from runtime.backends import create_backend
from runtime.backends.base import LocalBackend
from runtime.core.catalog import LocalModelSpec

log = get_logger("runtime.device")

DEFAULT_OOM_PATTERNS: tuple[str, ...] = (
    r"out of memory",
    r"failed to allocate",
    r"\bOOM\b",
    r"ErrorCode -5\b",
    r"CL_OUT_OF_RESOURCES",
    r"CL_MEM_OBJECT_ALLOCATION_FAILURE",
    r"ErrorOutOfDeviceMemory",
    r"vk::.*OutOfDeviceMemory",
    r"cudaMalloc failed",
    r"insufficient memory",
)


class EventRecorder(Protocol):
    def record(
        self,
        event: str,
        *,
        device: str,
        model_id: uuid.UUID | None = None,
        model_alias: str | None = None,
        reason: str | None = None,
        duration_ms: int | None = None,
        vram_used_mb: int | None = None,
        vram_budget_mb: int | None = None,
        request_id: str | uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...


class _NullRecorder:
    def record(self, event: str, *, device: str, **kwargs: Any) -> None:
        pass


@dataclass
class LoadedModel:
    spec: LocalModelSpec
    backend: LocalBackend
    semaphore: asyncio.Semaphore
    loaded_at: float
    last_used: float
    load_ms: int
    pinned: bool
    in_flight: int = 0  # termasuk yang sedang antre semaphore

    @property
    def active(self) -> int:
        return self.spec.replicas - self.semaphore._value  # noqa: SLF001


@dataclass(frozen=True, slots=True)
class Lease:
    spec: LocalModelSpec
    backend: LocalBackend
    device: str
    queue_ms: int
    load_ms: int


@dataclass
class DeviceStatus:
    device: str
    budget_mb: int
    used_mb: int
    free_mb: int
    loading: bool
    models: list[dict[str, Any]] = field(default_factory=list)


class DeviceManager:
    def __init__(
        self,
        device: str,
        budget_mb: int,
        *,
        min_residency_s: float = 60,
        queue_timeout_s: float = 30,
        allow_cpu_fallback: bool = False,
        backend_factory: Callable[[LocalModelSpec], LocalBackend] = create_backend,
        events: EventRecorder | None = None,
        oom_patterns: Sequence[str] = DEFAULT_OOM_PATTERNS,
        max_workers: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.device = device
        self.budget_mb = budget_mb
        self.min_residency_s = min_residency_s
        self.queue_timeout_s = queue_timeout_s
        self.allow_cpu_fallback = allow_cpu_fallback
        self._factory = backend_factory
        self._events: EventRecorder = events or _NullRecorder()
        self._oom_re = re.compile("|".join(oom_patterns), re.IGNORECASE)
        self._clock = clock
        self._loaded: dict[str, LoadedModel] = {}
        self._lock = asyncio.Lock()  # satu proses load/evict per device
        self._idle = asyncio.Event()
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix=f"rt-{device}"
        )

    # ---------------------------------------------------------------- status
    @property
    def used_mb(self) -> int:
        return sum(m.spec.vram_mb for m in self._loaded.values())

    @property
    def free_mb(self) -> int:
        return self.budget_mb - self.used_mb

    def is_loaded(self, alias: str) -> bool:
        return alias in self._loaded

    def loaded_aliases(self) -> list[str]:
        return list(self._loaded)

    def status(self) -> DeviceStatus:
        now = self._clock()
        models = [
            {
                "alias": m.spec.alias,
                "name": m.spec.upstream_name,
                "backend": m.spec.runtime_backend,
                "vram_mb": m.spec.vram_mb,
                "pinned": m.pinned,
                "in_flight": m.in_flight,
                "active": m.active,
                "queued": max(0, m.in_flight - m.active),
                "replicas": m.spec.replicas,
                "n_ctx": m.spec.n_ctx,
                "loaded_s_ago": round(now - m.loaded_at, 1),
                "idle_s": round(now - m.last_used, 1) if m.in_flight == 0 else 0.0,
                "load_ms": m.load_ms,
            }
            for m in self._loaded.values()
        ]
        return DeviceStatus(
            device=self.device,
            budget_mb=self.budget_mb,
            used_mb=self.used_mb,
            free_mb=self.free_mb,
            loading=self._lock.locked(),
            models=models,
        )

    # ---------------------------------------------------------------- events
    def _record(self, event: str, spec: LocalModelSpec | None = None, **kwargs: Any) -> None:
        self._events.record(
            event,
            device=self.device,
            model_id=spec.id if spec else None,
            model_alias=spec.alias if spec else kwargs.pop("model_alias", None),
            vram_used_mb=self.used_mb,
            vram_budget_mb=self.budget_mb,
            **kwargs,
        )

    def _notify_idle(self) -> None:
        event, self._idle = self._idle, asyncio.Event()
        event.set()

    async def _wait_idle(self, timeout: float) -> None:
        event = self._idle
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=max(timeout, 0.001))

    # --------------------------------------------------------------- acquire
    @contextlib.asynccontextmanager
    async def acquire(
        self, spec: LocalModelSpec, request_id: str | None = None
    ) -> AsyncIterator[Lease]:
        """Pinjam model untuk satu inferensi: load/evict bila perlu, antre per model."""
        start = time.monotonic()
        deadline = start + self.queue_timeout_s
        load_ms = 0
        if spec.alias not in self._loaded:
            load_ms = await self._ensure_loaded(spec, f"request:{request_id}", request_id, deadline)
        entry = self._loaded[spec.alias]
        entry.in_flight += 1  # tanpa await sejak cek di atas → tidak bisa di-evict di antaranya
        try:
            if entry.semaphore.locked():
                remaining = deadline - time.monotonic()
                try:
                    await asyncio.wait_for(entry.semaphore.acquire(), timeout=max(remaining, 0.001))
                except TimeoutError:
                    self._record(
                        "queue_timeout", spec, request_id=request_id, reason="model_queue_full"
                    )
                    raise ModelBusy(
                        f"{spec.alias} sibuk: antrean > {self.queue_timeout_s:g} detik"
                    ) from None
            else:
                await entry.semaphore.acquire()
        except BaseException:
            entry.in_flight -= 1
            self._notify_idle()
            raise
        queue_ms = max(0, int((time.monotonic() - start) * 1000) - load_ms)
        try:
            yield Lease(
                spec=entry.spec,
                backend=entry.backend,
                device=entry.backend.actual_device(),
                queue_ms=queue_ms,
                load_ms=load_ms,
            )
        finally:
            entry.semaphore.release()
            entry.in_flight -= 1
            entry.last_used = self._clock()
            self._notify_idle()

    async def _ensure_loaded(
        self, spec: LocalModelSpec, reason: str, request_id: str | None, deadline: float
    ) -> int:
        """Load model bila belum termuat. Kembalikan load_ms (0 bila sudah dimuat pihak lain)."""
        try:
            await asyncio.wait_for(
                self._lock.acquire(), timeout=max(deadline - time.monotonic(), 0.001)
            )
        except TimeoutError:
            self._record("queue_timeout", spec, request_id=request_id, reason="device_load_lock")
            raise ModelBusy(f"{self.device} sedang memuat model lain") from None
        try:
            if spec.alias in self._loaded:
                return 0
            if spec.vram_mb > self.budget_mb:
                self._record(
                    "load_failed",
                    spec,
                    request_id=request_id,
                    reason=f"vram_mb {spec.vram_mb} > budget {self.budget_mb}",
                )
                raise ModelLoadFailed(
                    f"{spec.alias}: vram_mb {spec.vram_mb} melebihi budget {self.device} "
                    f"{self.budget_mb} MB (periksa konfigurasi)"
                )
            await self._make_room(spec, request_id, deadline)
            return await self._load_with_retry(spec, reason, request_id)
        finally:
            self._lock.release()

    def _pick_victim(self) -> LoadedModel | None:
        now = self._clock()
        candidates = [
            m
            for m in self._loaded.values()
            if not m.pinned and m.in_flight == 0 and now - m.loaded_at >= self.min_residency_s
        ]
        return min(candidates, key=lambda m: m.last_used) if candidates else None

    def _next_residency_expiry(self) -> float | None:
        expiries = [
            m.loaded_at + self.min_residency_s
            for m in self._loaded.values()
            if not m.pinned and m.in_flight == 0
        ]
        return min(expiries) if expiries else None

    async def _make_room(
        self, spec: LocalModelSpec, request_id: str | None, deadline: float
    ) -> None:
        while self.free_mb < spec.vram_mb:
            victim = self._pick_victim()
            if victim is not None:
                await self._unload_entry(
                    victim,
                    event="evict",
                    reason=f"lru_evict_for:{spec.alias}",
                    request_id=request_id,
                )
                continue
            remaining = deadline - time.monotonic()
            now = self._clock()
            if remaining <= 0:
                self._record(
                    "queue_timeout", spec, request_id=request_id, reason="no_evictable_model"
                )
                raise ModelBusy(
                    f"{self.device} penuh: tidak ada model yang bisa di-evict untuk {spec.alias} "
                    f"dalam {self.queue_timeout_s:g} detik"
                )
            wait = remaining
            expiry = self._next_residency_expiry()
            if expiry is not None:
                wait = min(wait, max(expiry - now, 0.001))
            await self._wait_idle(wait)

    # ------------------------------------------------------------------ load
    def _is_oom(self, exc: BaseException) -> bool:
        return isinstance(exc, MemoryError) or bool(self._oom_re.search(str(exc)))

    @staticmethod
    def _next_ctx(spec: LocalModelSpec) -> LocalModelSpec | None:
        if not spec.config.get("auto_reduce_ctx"):
            return None
        current = spec.n_ctx
        if current is None:
            return None
        smaller = [int(c) for c in spec.config.get("ctx_fallback") or [] if int(c) < current]
        if not smaller:
            return None
        return spec.with_config(n_ctx=max(smaller))

    async def _load_with_retry(
        self, spec: LocalModelSpec, reason: str, request_id: str | None
    ) -> int:
        current = spec
        while True:
            try:
                backend = self._factory(current)
            except Exception as exc:  # backend belum terpasang / runtime_backend tak dikenal
                self._record("load_failed", current, request_id=request_id, reason=str(exc)[:500])
                raise
            backend.executor = self.executor
            started = self._clock()
            try:
                result = await backend.load()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await backend.unload()
                if self._is_oom(exc):
                    nxt = self._next_ctx(current)
                    self._record(
                        "oom",
                        current,
                        request_id=request_id,
                        reason=str(exc)[:500],
                        details={"n_ctx": current.n_ctx, "retry_n_ctx": nxt.n_ctx if nxt else None},
                    )
                    if nxt is not None:
                        log.warning("load_oom_retry", model=spec.alias, n_ctx=nxt.n_ctx)
                        current = nxt
                        continue
                    raise DeviceOOM(f"{spec.alias}: out of memory di {self.device}") from exc
                self._record("load_failed", current, request_id=request_id, reason=str(exc)[:500])
                if isinstance(exc, GatewayError):
                    raise
                raise ModelLoadFailed(f"{spec.alias}: load gagal: {exc}") from exc

            actual = backend.actual_device()
            if actual == "cpu" and not self.allow_cpu_fallback:
                with contextlib.suppress(Exception):
                    await backend.unload()
                self._record(
                    "load_failed", current, request_id=request_id, reason="cpu_not_allowed"
                )
                raise DeviceUnavailable(
                    f"{spec.alias} termuat di CPU; ditolak (ALLOW_CPU_FALLBACK=false)"
                )
            now = self._clock()
            load_ms = result.load_ms or int((now - started) * 1000)
            self._loaded[spec.alias] = LoadedModel(
                spec=current,
                backend=backend,
                semaphore=asyncio.Semaphore(current.replicas),
                loaded_at=now,
                last_used=now,
                load_ms=load_ms,
                pinned=current.is_pinned,
            )
            self._record(
                "load",
                current,
                request_id=request_id,
                reason=reason,
                duration_ms=load_ms,
                details={"actual_device": actual, "n_ctx": current.n_ctx, **result.details},
            )
            return load_ms

    async def load(self, spec: LocalModelSpec, reason: str = "manual", *, pin: bool = False) -> int:
        """Load eksplisit (warmup / admin). pin=True menandai pinned di memori."""
        load_ms = 0
        if spec.alias not in self._loaded:
            deadline = time.monotonic() + self.queue_timeout_s
            load_ms = await self._ensure_loaded(spec, reason, None, deadline)
        if pin:
            self._loaded[spec.alias].pinned = True
        return load_ms

    # ---------------------------------------------------------------- unload
    async def _unload_entry(
        self, entry: LoadedModel, *, event: str, reason: str, request_id: str | None = None
    ) -> None:
        self._loaded.pop(entry.spec.alias, None)
        started = self._clock()
        try:
            await entry.backend.unload()
        except Exception as exc:  # noqa: BLE001
            log.error("unload_failed", model=entry.spec.alias, error=str(exc))
        self._record(
            event,
            entry.spec,
            reason=reason,
            request_id=request_id,
            duration_ms=int((self._clock() - started) * 1000),
        )

    async def unload(self, alias: str, reason: str = "manual", *, force: bool = False) -> bool:
        async with self._lock:
            entry = self._loaded.get(alias)
            if entry is None:
                return False
            if entry.in_flight and not force:
                raise ModelBusy(f"{alias} sedang melayani {entry.in_flight} request")
            await self._unload_entry(entry, event="unload", reason=reason)
            return True

    async def unload_all(self, reason: str) -> None:
        for alias in list(self._loaded):
            entry = self._loaded.get(alias)
            if entry is not None:
                await self._unload_entry(entry, event="unload", reason=reason)

    def set_pinned(self, alias: str, pinned: bool) -> None:
        if alias in self._loaded:
            self._loaded[alias].pinned = pinned

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
