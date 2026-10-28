"""Runtime app (tanpa lifespan/DB/hardware) + adapter gateway LocalRuntimeProvider di atasnya."""

import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx2
import pytest

from app.core.config import get_settings
from app.schemas.catalog import ModelConfig, ProviderConfig
from app.schemas.unified import (
    UnifiedChatRequest,
    UnifiedCompletionRequest,
    UnifiedImageRequest,
    UnifiedMessage,
)
from app.services.providers.local_runtime_provider import LocalRuntimeProvider
from app.utils import errors as e
from runtime.core.catalog import RuntimeCatalog
from runtime.core.lifespan import RuntimeStartError, build_state, check_devices
from runtime.device.probe import DeviceInfo, DeviceProbe
from runtime.main import create_runtime_app
from tests.fakes.fake_backend import FakeBackend, spec

SPECS = {
    "chat-fast": spec("local/chat-fast", 1000, tokens=["Ha", "lo"]),
    "chat-slow": spec("local/chat-slow", 1000, infer_delay_s=0.4, tokens=["a", "b", "c"]),
    "big-a": spec("local/big-a", 5000),
    "big-b": spec("local/big-b", 5000),
    "img": spec("local/img", 2500, device="npu"),
}


class _Events:
    def __init__(self) -> None:
        self.items: list[str] = []

    def record(self, event: str, **kw) -> None:
        self.items.append(event)

    async def drain(self) -> None:
        pass


def _probe(gpu=True, npu=True) -> DeviceProbe:
    return DeviceProbe(
        gpu=DeviceInfo(available=gpu, name="iGPU"), npu=DeviceInfo(available=npu, name="NPU")
    )


@pytest.fixture
def runtime_app():
    settings = get_settings().model_copy(
        update={"runtime_queue_timeout_s": 0.3, "runtime_min_residency_s": 60}
    )
    catalog = RuntimeCatalog(session_factory=None)  # type: ignore[arg-type]
    catalog.set(dict(SPECS))
    app = create_runtime_app(settings, with_lifespan=False)
    app.state.rt = build_state(
        settings,
        _probe(),
        catalog,
        _Events(),  # type: ignore[arg-type]
        backend_factory=FakeBackend,
    )
    yield app
    for m in app.state.rt.managers.values():
        m.close()


TOKEN = {"X-Runtime-Token": get_settings().runtime_token.get_secret_value()}


def _client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://rt")


async def test_requires_runtime_token(runtime_app):
    async with _client(runtime_app) as c:
        for path in ("/v1/chat/completions", "/runtime/status"):
            r = await (
                c.post(path, json={"model": "chat-fast"}) if path.startswith("/v1") else c.get(path)
            )
            assert r.status_code == 401
            assert r.json()["error"]["code"] == "invalid_api_key"
        r = await c.get("/runtime/status", headers={"X-Runtime-Token": "wrong"})
        assert r.status_code == 401
        assert (await c.get("/health/live")).status_code == 200


async def test_chat_non_stream_has_x_runtime(runtime_app):
    async with _client(runtime_app) as c:
        r = await c.post(
            "/v1/chat/completions", headers=TOKEN, json={"model": "chat-fast", "messages": []}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "Halo"
    assert body["x_runtime"]["device"] == "gpu" and body["x_runtime"]["backend"] == "fake"
    assert body["x_runtime"]["load_ms"] > 0  # load pertama tercatat


async def test_chat_stream_x_runtime_on_last_chunk(runtime_app):
    async with _client(runtime_app) as c:
        r = await c.post(
            "/v1/chat/completions", headers=TOKEN, json={"model": "chat-fast", "stream": True}
        )
    lines = [ln[6:] for ln in r.text.split("\n\n") if ln.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(x) for x in lines[:-1]]
    assert (
        "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
        == "Halo"
    )
    assert chunks[-1]["x_runtime"]["device"] == "gpu"
    assert all("x_runtime" not in c for c in chunks[:-1])


async def test_status_fast_while_inference_running(runtime_app):
    async with _client(runtime_app) as c:
        infer = asyncio.ensure_future(
            c.post(
                "/v1/chat/completions", headers=TOKEN, json={"model": "chat-slow", "messages": []}
            )
        )
        await asyncio.sleep(0.15)
        start = time.perf_counter()
        r = await c.get("/runtime/status", headers=TOKEN)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert r.status_code == 200 and elapsed_ms < 50
        models = r.json()["devices"]["gpu"]["models"]
        assert models[0]["alias"] == "local/chat-slow" and models[0]["active"] == 1
        assert (await infer).status_code == 200


async def test_model_busy_is_503_and_errors_unknown_model(runtime_app):
    async with _client(runtime_app) as c:
        assert (
            await c.post("/v1/chat/completions", headers=TOKEN, json={"model": "big-a"})
        ).status_code == 200
        r = await c.post("/v1/chat/completions", headers=TOKEN, json={"model": "big-b"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "model_busy"
        r = await c.post("/v1/chat/completions", headers=TOKEN, json={"model": "nope"})
        assert r.status_code == 404
        r = await c.post("/v1/embeddings", headers=TOKEN, json={"model": "chat-fast"})
        assert r.status_code == 404  # tidak ada embedding lokal


async def test_image_generations_and_edits(runtime_app):
    async with _client(runtime_app) as c:
        r = await c.post(
            "/v1/images/generations",
            headers=TOKEN,
            json={"model": "img", "prompt": "kucing", "image": "abaikan", "n": 2},
        )
        assert r.status_code == 200 and len(r.json()["data"]) == 2
        assert "image" not in FakeBackend.instances[-1].last_image_request  # murni t2i
        r = await c.post("/v1/images/edits", headers=TOKEN, json={"model": "img", "prompt": "x"})
        assert r.status_code == 400
        r = await c.post(
            "/v1/images/edits",
            headers=TOKEN,
            json={"model": "img", "prompt": "malam hari", "image": "iVBORw0K", "strength": 0.5},
        )
        assert r.status_code == 200
        assert FakeBackend.instances[-1].last_image_request["image"] == "iVBORw0K"


async def test_manual_load_unload(runtime_app):
    async with _client(runtime_app) as c:
        r = await c.post("/runtime/models/local/big-a/load?pin=true", headers=TOKEN)
        assert r.json() == {
            "model": "local/big-a",
            "loaded": True,
            "load_ms": r.json()["load_ms"],
            "pinned": True,
        }
        r = await c.post("/runtime/models/big-a/unload", headers=TOKEN)
        assert r.json() == {"model": "local/big-a", "unloaded": True}


def test_missing_device_fails_start_unless_cpu_fallback():
    catalog = RuntimeCatalog(session_factory=None)  # type: ignore[arg-type]
    catalog.set({"img": SPECS["img"]})
    events = _Events()
    settings = get_settings()
    with pytest.raises(RuntimeStartError, match="NPU"):
        check_devices(settings, _probe(npu=False), catalog, events)  # type: ignore[arg-type]
    assert events.items == ["device_error"]
    check_devices(
        settings.model_copy(update={"allow_cpu_fallback": True}), _probe(npu=False), catalog, events
    )  # type: ignore[arg-type]
    check_devices(settings, _probe(), catalog, events)  # type: ignore[arg-type]


# ------------------------------------------------------- adapter gateway → runtime
def _local_provider(runtime_app) -> LocalRuntimeProvider:
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=runtime_app))
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="openvino",
        kind="local",
        display_name="openvino",
        base_url="http://rt/v1",
        api_key_env="RUNTIME_TOKEN",
    )
    return LocalRuntimeProvider(cfg, http, get_settings())


def _model(name: str, **kw) -> ModelConfig:
    return ModelConfig(
        id=uuid.uuid4(),
        alias=f"local/{name}",
        provider_code="openvino",
        upstream_name=name,
        model_type=kw.pop("model_type", "chat"),
        device="gpu",
        runtime_backend="fake",
        **kw,
    )


REQ = UnifiedChatRequest(messages=[UnifiedMessage(role="user", content="hi")])


async def test_provider_chat_runtime_meta(runtime_app):
    p = _local_provider(runtime_app)
    resp = await p.chat(_model("chat-fast"), REQ)
    assert resp.content == "Halo"
    assert resp.runtime_meta.device == "gpu" and resp.runtime_meta.backend == "fake"
    assert resp.usage.prompt_tokens == 4


async def test_provider_stream_runtime_meta_last(runtime_app):
    p = _local_provider(runtime_app)
    chunks = [c async for c in p.chat_stream(_model("chat-fast"), REQ)]
    assert "".join(c.delta_content or "" for c in chunks) == "Halo"
    assert chunks[-1].runtime_meta is not None and chunks[-1].runtime_meta.device == "gpu"
    assert any(c.usage for c in chunks)


async def test_provider_model_busy_is_retryable_for_fallback(runtime_app):
    p = _local_provider(runtime_app)
    await p.chat(_model("big-a"), REQ)
    with pytest.raises(e.ModelBusy) as info:
        await p.chat(_model("big-b"), REQ)
    assert info.value.retryable  # router akan fallback ke kandidat berikutnya
    with pytest.raises(e.ModelBusy):
        async for _ in p.chat_stream(_model("big-b"), REQ):
            pass


async def test_provider_capability_and_images(runtime_app):
    p = _local_provider(runtime_app)
    with pytest.raises(e.CapabilityNotSupported):
        await p.completion(_model("chat-fast"), UnifiedCompletionRequest(prompt="x"))
    img = await p.generate_images(
        _model("img", model_type="image"), UnifiedImageRequest(prompt="kucing", n=2, seed=10)
    )
    assert [i.seed for i in img.images] == [10, 11]
    assert img.images[0].png_bytes.startswith(b"\x89PNG") and len(img.images[0].sha256) == 64
    assert img.runtime_meta.device == "npu"


async def test_provider_health_degraded_when_runtime_down():
    http = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda r: (_ for _ in ()).throw(httpx2.ConnectError("refused", request=r))
        )
    )
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="openvino",
        kind="local",
        display_name="l",
        base_url="http://127.0.0.1:1/v1",
        api_key_env="RUNTIME_TOKEN",
    )
    health = await LocalRuntimeProvider(cfg, http, get_settings()).health()
    assert not health.ok and "tidak terjangkau" in health.detail


def test_supervisor_script_restarts_on_crash():
    text = (Path(__file__).resolve().parents[3] / "scripts" / "start-runtime.bat").read_text()
    assert "run_runtime.py" in text and "goto loop" in text and "runtime-supervisor.log" in text
