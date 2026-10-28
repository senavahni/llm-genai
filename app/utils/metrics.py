"""Metrik Prometheus gateway (TASK-18). Registry sendiri (bukan default global) agar gateway &
runtime tidak bentrok saat diuji dalam satu proses. Label TIDAK memuat project/key (kardinalitas
tinggi; detail per project ada di DB)."""

from typing import TYPE_CHECKING, Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

if TYPE_CHECKING:
    from app.services.context import RequestCtx

REGISTRY = CollectorRegistry(auto_describe=True)
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300)

REQUESTS = Counter(
    "gateway_requests_total",
    "Request publik selesai",
    ["endpoint", "provider", "model", "status"],
    registry=REGISTRY,
)
LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Latensi total request",
    ["endpoint", "provider"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)
TTFT = Histogram(
    "gateway_ttft_seconds",
    "Waktu sampai chunk pertama (stream)",
    ["provider"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)
TOKENS = Counter("gateway_tokens_total", "Token", ["provider", "model", "kind"], registry=REGISTRY)
COST = Counter("gateway_cost_usd_total", "Biaya USD", ["provider", "model"], registry=REGISTRY)
UPSTREAM_ERRORS = Counter(
    "gateway_upstream_errors_total",
    "Attempt yang gagal per provider",
    ["provider", "error_type"],
    registry=REGISTRY,
)
INFLIGHT = Gauge(
    "gateway_inflight_requests", "Request sedang diproses", ["endpoint"], registry=REGISTRY
)
FALLBACKS = Counter(
    "gateway_fallbacks_total",
    "Request yang sukses setelah fallback ke kandidat berikutnya",
    ["route"],
    registry=REGISTRY,
)
BY_DEVICE = Counter(
    "gateway_requests_by_device_total",
    "Request per device aktual (cpu harus 0 di produksi, alarm NF9)",
    ["device"],
    registry=REGISTRY,
)
IMAGES = Counter("gateway_images_total", "Gambar dihasilkan", ["model"], registry=REGISTRY)

# label device selalu ada walau nol → alarm `device="cpu"` bisa dibuat sejak awal
for _device in ("remote", "gpu", "npu", "cpu"):
    BY_DEVICE.labels(_device)


def request_started(endpoint: str) -> None:
    INFLIGHT.labels(endpoint).inc()


def observe_request(ctx: "RequestCtx", record: dict[str, Any]) -> None:
    """Dipanggil usage_service.finish (tepat sekali per request yang sudah `start`)."""
    provider = record["provider_code"]
    model = record["model_alias"]
    INFLIGHT.labels(ctx.endpoint).dec()
    REQUESTS.labels(ctx.endpoint, provider, model, record["status"]).inc()
    LATENCY.labels(ctx.endpoint, provider).observe(record["latency_ms"] / 1000)
    if record["ttft_ms"] is not None:
        TTFT.labels(provider).observe(record["ttft_ms"] / 1000)
    if record["prompt_tokens"]:
        TOKENS.labels(provider, model, "prompt").inc(record["prompt_tokens"])
    if record["completion_tokens"]:
        TOKENS.labels(provider, model, "completion").inc(record["completion_tokens"])
    cost = float(record["cost_usd"])
    if cost:
        COST.labels(provider, model).inc(cost)
    for attempt in record["attempts"]:
        if attempt["status"] == "error":
            UPSTREAM_ERRORS.labels(
                attempt["provider_code"], attempt["error_type"] or "unknown"
            ).inc()
    if record["status"] == "success" and len(record["attempts"]) > 1:
        FALLBACKS.labels(ctx.requested_model).inc()
    if record["device"]:
        BY_DEVICE.labels(record["device"]).inc()
    if record["image_count"]:
        IMAGES.labels(model).inc(record["image_count"])


def render() -> bytes:
    return generate_latest(REGISTRY)
