"""TASK-18: /health/live, /health/ready (ready/degraded/not_ready), /metrics."""

import statistics
import time
import uuid

import httpx
import httpx2
import pytest
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import load_settings
from app.core.registry import ProviderRegistry
from app.main import create_app
from app.schemas.catalog import ProviderConfig
from app.services import health_service as hs
from app.services.key_service import key_service
from app.services.providers.local_runtime_provider import LocalRuntimeProvider

pytestmark = pytest.mark.integration

RUNTIME_METRICS = (
    "# TYPE runtime_device_memory_used_mb gauge\n"
    'runtime_device_memory_used_mb{device="gpu"} 4900.0\n'
    'runtime_device_memory_used_mb{device="npu"} 6100.0\n'
    "# TYPE runtime_model_loaded gauge\n"
    'runtime_model_loaded{device="npu",model="local/sd-1.5",pinned="true"} 1.0\n'
)


def _runtime_handler(*, pinned_ok=True, down=False):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if down:
            raise httpx2.ConnectError("refused", request=request)
        if request.url.path == "/health/ready":
            body = {
                "ready": pinned_ok,
                "status": "ok" if pinned_ok else "warming_up",
                "progress": "loaded 2/2" if pinned_ok else "loaded 1/2",
                "devices": {"gpu": {"ok": True}, "npu": {"ok": True}},
                "pinned": {"local/sd-1.5": True, "local/qwen2.5-coder-1.5b": pinned_ok},
                "memory": {
                    "gpu": {"used_mb": 0, "budget_mb": 5300},
                    "npu": {"used_mb": 6100, "budget_mb": 6200},
                },
            }
            return httpx2.Response(200 if pinned_ok else 503, json=body)
        if request.url.path == "/metrics":
            return httpx2.Response(200, text=RUNTIME_METRICS)
        return httpx2.Response(404)

    return handler


def _app(handler):
    hs.health_service.invalidate()
    hs.health_service._runtime_metrics = None
    settings = load_settings()
    app = create_app(settings)
    registry = ProviderRegistry(
        settings, http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="openvino",
        kind="local",
        display_name="l",
        base_url="http://127.0.0.1:8100/v1",
        api_key_env="RUNTIME_TOKEN",
    )
    registry.providers = {"openvino": LocalRuntimeProvider(cfg, registry.http, settings)}
    registry.disabled = {"openai": "API key kosong"}
    app.state.registry = registry
    return app


def _client(app, ip="127.0.0.1"):
    transport = httpx.ASGITransport(app=app, client=(ip, 5555))
    return httpx.AsyncClient(transport=transport, base_url="http://t")


async def test_ready_when_runtime_and_pinned_ok(db):
    async with _client(_app(_runtime_handler())) as c:
        r = await c.get("/health/ready")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ready", body
    assert body["database"]["ok"] is True and "latency_ms" in body["database"]
    assert body["runtime"]["devices"]["npu"] == {"ok": True, "used_mb": 6100, "budget_mb": 6200}
    assert body["providers"]["openai"]["ok"] is None  # disabled tidak menurunkan status


async def test_degraded_when_runtime_down_or_pinned_missing(db):  # AC1
    async with _client(_app(_runtime_handler(down=True))) as c:
        r = await c.get("/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "degraded"
    assert r.json()["runtime"]["ok"] is False
    async with _client(_app(_runtime_handler(pinned_ok=False))) as c:
        body = (await c.get("/health/ready")).json()
    assert body["status"] == "degraded" and body["runtime"]["progress"] == "loaded 1/2"


async def test_not_ready_when_db_down(db, monkeypatch):  # AC1
    dead = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/none")
    monkeypatch.setattr(hs, "get_engine", lambda: dead)
    async with _client(_app(_runtime_handler())) as c:
        r = await c.get("/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"
    await dead.dispose()


async def test_details_hidden_for_remote_clients(db):
    app = _app(_runtime_handler(down=True))
    async with _client(app, ip="10.1.2.3") as c:
        body = (await c.get("/health/ready")).json()
        assert body["providers"]["openvino"] == {"ok": False}
        assert (await c.get("/metrics")).status_code == 403
        admin_key, _ = await _admin_key()
        r = await c.get("/metrics", headers={"Authorization": f"Bearer {admin_key}"})
        assert r.status_code == 200


async def _admin_key():
    from app.core.database import SessionLocal

    async with SessionLocal() as s:
        return await key_service.create_key(s, project_id=None, name="adm", role="admin")


async def test_metrics_parse_and_include_runtime(api):  # AC2 & AC4
    hs.health_service._runtime_metrics = None

    async def scrape(c):
        text = (await c.get("/metrics")).text
        families = {f.name: f for f in text_string_to_metric_families(text)}
        return text, families

    def total(families, name, **labels):
        fam = families.get(name)
        return sum(
            s.value
            for s in (fam.samples if fam else [])
            if s.name.endswith("_total") and all(s.labels.get(k) == v for k, v in labels.items())
        )

    async with api.client() as c:
        _, before = await scrape(c)
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "local", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 200
        text, after = await scrape(c)
    assert total(after, "gateway_requests", endpoint="chat.completions", status="success") == (
        total(before, "gateway_requests", endpoint="chat.completions", status="success") + 1
    )
    assert total(after, "gateway_requests_by_device", device="gpu") > total(
        before, "gateway_requests_by_device", device="gpu"
    )
    assert 'gateway_requests_by_device_total{device="cpu"} 0.0' in text  # alarm NF9


async def test_metrics_merges_runtime_metrics(db):  # AC4
    async with _client(_app(_runtime_handler())) as c:
        text = (await c.get("/metrics")).text
    names = {f.name for f in text_string_to_metric_families(text)}
    assert {"runtime_device_memory_used_mb", "runtime_model_loaded", "gateway_requests"} <= names


async def test_live_fast(db):  # AC3
    app = _app(_runtime_handler())
    async with _client(app) as c:
        times = []
        for _ in range(20):
            t = time.perf_counter()
            r = await c.get("/health/live")
            times.append(time.perf_counter() - t)
    assert r.json()["status"] == "ok" and "uptime_s" in r.json() and r.json()["version"]
    assert statistics.median(times) < 0.010
