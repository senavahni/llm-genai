"""LGW-V1-02: /health/ready menandai route yang seluruh kandidatnya lokal (embed-local) degraded
saat runtime mati; route campuran/remote tidak ikut."""

import uuid
from types import SimpleNamespace

from app.core.registry import ModelCatalog
from app.schemas.catalog import ModelConfig, RouteConfig, RouteTarget
from app.services.health_service import HealthService


def _model(alias: str, device: str) -> ModelConfig:
    return ModelConfig(
        id=uuid.uuid4(),
        alias=alias,
        provider_code="openvino" if device != "remote" else "openai",
        upstream_name=alias.split("/")[-1],
        model_type="embedding",
        device=device,
    )


def _registry() -> SimpleNamespace:
    catalog = ModelCatalog()
    models = {
        "local/qwen3-embedding-0.6b": _model("local/qwen3-embedding-0.6b", "gpu"),
        "openai/text-embedding-3-small": _model("openai/text-embedding-3-small", "remote"),
    }
    routes = {
        "embed-local": RouteConfig(
            "embed-local", targets=(RouteTarget("local/qwen3-embedding-0.6b"),)
        ),
        "embed-default": RouteConfig(
            "embed-default", targets=(RouteTarget("openai/text-embedding-3-small"),)
        ),
        "mixed": RouteConfig(
            "mixed",
            targets=(
                RouteTarget("local/qwen3-embedding-0.6b"),
                RouteTarget("openai/text-embedding-3-small", priority=2),
            ),
        ),
        "off": RouteConfig(
            "off", is_enabled=False, targets=(RouteTarget("local/qwen3-embedding-0.6b"),)
        ),
    }
    catalog.replace(models, routes)
    return SimpleNamespace(
        providers={"openvino": SimpleNamespace(runtime_request=object())}, catalog=catalog
    )


def test_runtime_down_marks_local_only_routes_degraded():
    providers = {"openvino": {"ok": False, "detail": "runtime tidak terjangkau: ConnectError"}}
    section = HealthService.runtime_section(_registry(), providers)  # type: ignore[arg-type]
    assert section["ok"] is False
    assert section["degraded_routes"] == ["embed-local"]


def test_runtime_ok_has_no_degraded_routes():
    providers = {
        "openvino": {
            "ok": True,
            "extra": {
                "devices": {"gpu": {"ok": True}},
                "pinned": {"local/qwen3-embedding-0.6b": True},
            },
        }
    }
    section = HealthService.runtime_section(_registry(), providers)  # type: ignore[arg-type]
    assert section["ok"] is True and "degraded_routes" not in section
