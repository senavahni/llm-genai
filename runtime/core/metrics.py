"""Metrik Prometheus Local Runtime (TASK-18). Event (load/evict/oom) dicatat lewat
EventService.record; memori device, model termuat & antrean dihitung saat scrape dari state."""

from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

if TYPE_CHECKING:
    from runtime.core.state import RuntimeState

REGISTRY = CollectorRegistry(auto_describe=True)

DEVICE_USED = Gauge(
    "runtime_device_memory_used_mb", "Memori model termuat", ["device"], registry=REGISTRY
)
DEVICE_BUDGET = Gauge(
    "runtime_device_memory_budget_mb", "Budget memori device", ["device"], registry=REGISTRY
)
MODEL_LOADED = Gauge(
    "runtime_model_loaded", "Model termuat (0/1)", ["model", "device", "pinned"], registry=REGISTRY
)
LOAD_SECONDS = Histogram(
    "runtime_model_load_seconds",
    "Waktu load model (termasuk compile)",
    ["model", "device"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)
EVICTIONS = Counter(
    "runtime_evictions_total", "Model di-evict LRU", ["model", "device"], registry=REGISTRY
)
OOM = Counter("runtime_oom_total", "Load gagal karena OOM", ["model", "device"], registry=REGISTRY)
QUEUE_WAIT = Histogram(
    "runtime_queue_wait_seconds",
    "Waktu antre per model",
    ["model"],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge("runtime_queue_depth", "Request antre per model", ["model"], registry=REGISTRY)
TOKENS_PER_SECOND = Histogram(
    "runtime_tokens_per_second",
    "Kecepatan generate",
    ["model"],
    buckets=(1, 2, 4, 6, 8, 10, 15, 20, 30, 50, 100),
    registry=REGISTRY,
)
IMAGE_SECONDS = Histogram(
    "runtime_image_seconds",
    "Waktu generate per gambar",
    ["model", "size"],
    buckets=(1, 5, 10, 15, 20, 30, 45, 60, 120),
    registry=REGISTRY,
)
_seen_loaded: set[tuple[str, str, str]] = set()


def on_event(event: str, model: str | None, device: str, duration_ms: int | None) -> None:
    model = model or "-"
    if event == "load" and duration_ms is not None:
        LOAD_SECONDS.labels(model, device).observe(duration_ms / 1000)
    elif event == "evict":
        EVICTIONS.labels(model, device).inc()
    elif event == "oom":
        OOM.labels(model, device).inc()


def observe_generation(model: str, completion_tokens: int, seconds: float) -> None:
    if completion_tokens > 0 and seconds > 0:
        TOKENS_PER_SECOND.labels(model).observe(completion_tokens / seconds)


def refresh(state: "RuntimeState") -> None:
    """Snapshot state saat scrape (gauge yang tidak termuat lagi di-set 0)."""
    current: set[tuple[str, str, str]] = set()
    for device, manager in state.managers.items():
        status = manager.status()
        DEVICE_USED.labels(device).set(status.used_mb)
        DEVICE_BUDGET.labels(device).set(status.budget_mb)
        for m in status.models:
            key = (m["alias"], device, str(bool(m["pinned"])).lower())
            current.add(key)
            MODEL_LOADED.labels(*key).set(1)
            QUEUE_DEPTH.labels(m["alias"]).set(m["queued"])
    for key in _seen_loaded - current:
        MODEL_LOADED.labels(*key).set(0)
        QUEUE_DEPTH.labels(key[0]).set(0)
    _seen_loaded.clear()
    _seen_loaded.update(current)


def render(state: "RuntimeState | None") -> bytes:
    if state is not None:
        refresh(state)
    return generate_latest(REGISTRY)
