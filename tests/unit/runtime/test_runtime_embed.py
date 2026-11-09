"""LGW-V1-02/03: `/v1/embeddings` runtime + adapter gateway, whitelist RUNTIME_ALLOWED_MODELS.
Tanpa DB/hardware: backend embedding nyata di atas `openvino_genai` palsu."""

import uuid
from dataclasses import replace

import httpx2
import pytest

from app.core.config import Settings, get_settings
from app.schemas.catalog import ModelConfig, ProviderConfig
from app.services.providers.local_runtime_provider import LocalRuntimeProvider
from app.utils import errors as e
from runtime.backends import ov_common, ov_embed_backend
from runtime.backends.ov_embed_backend import OVEmbedBackend
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog
from runtime.core.lifespan import build_state
from runtime.device.probe import DeviceInfo, DeviceProbe
from runtime.main import create_runtime_app
from tests.fakes import fake_genai
from tests.fakes.fake_backend import FakeBackend, spec

EMBED_ALIAS = "local/qwen3-embedding-0.6b"
TOKEN = {"X-Runtime-Token": get_settings().runtime_token.get_secret_value()}


class _Events:
    def record(self, event: str, **kw) -> None:
        pass

    async def drain(self) -> None:
        pass


def _factory(s: LocalModelSpec):
    return OVEmbedBackend(s) if s.runtime_backend == "openvino_embed" else FakeBackend(s)


@pytest.fixture
def specs(tmp_path, monkeypatch):
    monkeypatch.setattr(ov_embed_backend, "genai", fake_genai.module)
    ov_common._verified.clear()
    model = tmp_path / "qwen3-embedding-0.6b-int8"
    model.mkdir()
    (model / "openvino_model.xml").write_text("ir")
    embed = LocalModelSpec(
        alias=EMBED_ALIAS,
        upstream_name="qwen3-embedding-0.6b",
        device="gpu",
        runtime_backend="openvino_embed",
        model_type="embedding",
        artifact_path=str(model),
        vram_mb=1200,
        is_pinned=True,
        config={"device": "GPU", "max_batch": 4, "cache_dir": str(tmp_path / "cache")},
    )
    return {
        "qwen3-embedding-0.6b": embed,
        "qwen2.5-7b": spec("local/qwen2.5-7b", 4900, pinned=True),
        "sd15": spec("local/sd-1.5", 3300, device="npu"),
    }


def _app(specs, allowed=()):
    settings: Settings = get_settings().model_copy(update={"runtime_queue_timeout_s": 5})
    catalog = RuntimeCatalog(session_factory=None, allowed=allowed)  # type: ignore[arg-type]
    catalog.set(dict(specs))
    app = create_runtime_app(settings, with_lifespan=False)
    probe = DeviceProbe(gpu=DeviceInfo(available=True), npu=DeviceInfo(available=True))
    app.state.rt = build_state(settings, probe, catalog, _Events(), backend_factory=_factory)  # type: ignore[arg-type]
    return app


def _client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://rt")


def _provider(http: httpx2.AsyncClient, base_url: str = "http://rt/v1") -> LocalRuntimeProvider:
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="openvino",
        kind="local",
        display_name="openvino",
        base_url=base_url,
        api_key_env="RUNTIME_TOKEN",
    )
    return LocalRuntimeProvider(cfg, http, get_settings())


EMBED_MODEL = ModelConfig(
    id=uuid.uuid4(),
    alias=EMBED_ALIAS,
    provider_code="openvino",
    upstream_name="qwen3-embedding-0.6b",
    model_type="embedding",
    device="gpu",
    runtime_backend="openvino_embed",
)


def _close(app) -> None:
    for m in app.state.rt.managers.values():
        m.close()


# ------------------------------------------------------------------ endpoint
async def test_runtime_embeddings_endpoint_requires_token_and_returns_x_runtime(specs):
    app = _app(specs)
    async with _client(app) as c:
        body = {"model": "qwen3-embedding-0.6b", "input": ["a b", "c"]}
        assert (await c.post("/v1/embeddings", json=body)).status_code == 401
        r = await c.post("/v1/embeddings", json=body, headers=TOKEN)
    _close(app)
    assert r.status_code == 200
    data = r.json()
    assert [d["index"] for d in data["data"]] == [0, 1]
    assert len(data["data"][0]["embedding"]) == fake_genai.TextEmbeddingPipeline.dim
    assert data["usage"]["prompt_tokens"] == (2 + 2) + (1 + 2)
    assert data["x_runtime"]["device"] == "gpu"
    assert data["x_runtime"]["backend"] == "openvino_embed"


async def test_embeddings_on_chat_model_is_capability_error(specs):
    app = _app(specs)
    async with _client(app) as c:
        r = await c.post(
            "/v1/embeddings", json={"model": "qwen2.5-7b", "input": "x"}, headers=TOKEN
        )
    _close(app)
    assert r.status_code == 400 and r.json()["error"]["code"] == "capability_not_supported"


async def test_gateway_provider_embed_through_runtime(specs):
    app = _app(specs)
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    resp = await _provider(http).embed(EMBED_MODEL, ["halo dunia", "apa kabar"], None, {})
    _close(app)
    assert len(resp.vectors) == 2
    assert resp.vectors[0] == pytest.approx(fake_genai.TextEmbeddingPipeline.vector("halo dunia"))
    assert resp.usage.prompt_tokens == 8  # dari tokenizer runtime, bukan perkiraan
    assert resp.runtime_meta is not None and resp.runtime_meta.device == "gpu"


async def test_gateway_provider_runtime_down_is_provider_unavailable():
    http = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda r: (_ for _ in ()).throw(httpx2.ConnectError("refused", request=r))
        )
    )
    with pytest.raises(e.ProviderUnavailable) as info:
        await _provider(http, "http://127.0.0.1:1/v1").embed(EMBED_MODEL, ["x"], None, {})
    assert info.value.code == "provider_unavailable" and info.value.http_status == 503


# ----------------------------------------------------------------- whitelist
async def test_whitelist_only_embed_model_in_catalog_and_warmup(specs):
    app = _app(specs, allowed=[EMBED_ALIAS])
    state = app.state.rt
    assert sorted(state.catalog.specs) == ["qwen3-embedding-0.6b"]
    await state.warmup()
    async with _client(app) as c:
        status = (await c.get("/runtime/status", headers=TOKEN)).json()
        ready = await c.get("/health/ready")
    _close(app)
    loaded = [m["alias"] for d in status["devices"].values() for m in d["models"]]
    assert loaded == [EMBED_ALIAS]  # hanya satu model termuat, di GPU
    assert status["devices"]["gpu"]["models"][0]["pinned"] is True
    assert status["allowed_models"] == [EMBED_ALIAS]
    assert status["rejected_not_whitelisted"] == ["local/qwen2.5-7b", "local/sd-1.5"]
    assert ready.status_code == 200 and ready.json()["pinned"] == {EMBED_ALIAS: True}


@pytest.mark.parametrize("name", ["local/qwen2.5-7b", "qwen2.5-7b", "sd15"])
async def test_whitelist_rejects_manual_load_and_inference(specs, name):
    app = _app(specs, allowed=[EMBED_ALIAS])
    async with _client(app) as c:
        r = await c.post(f"/runtime/models/{name}/load", headers=TOKEN)
        chat = await c.post(
            "/v1/chat/completions",
            json={"model": name, "messages": [{"role": "user", "content": "hi"}]},
            headers=TOKEN,
        )
    loaded = app.state.rt.managers["gpu"].loaded_aliases()
    _close(app)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_whitelisted"
    assert chat.json()["error"]["code"] == "model_not_whitelisted"
    assert loaded == []


async def test_whitelist_applies_on_catalog_reload(specs, monkeypatch):
    app = _app(specs, allowed=["qwen3-embedding-0.6b"])  # upstream_name juga boleh

    async def fake_load():
        app.state.rt.catalog.set(dict(specs))  # DB: semua model enabled
        return app.state.rt.catalog.specs

    monkeypatch.setattr(app.state.rt.catalog, "load", fake_load)
    async with _client(app) as c:
        r = await c.post("/runtime/catalog/reload", headers=TOKEN)
    if app.state.rt.warmup_task is not None:
        await app.state.rt.warmup_task
    loaded = app.state.rt.managers["gpu"].loaded_aliases()
    _close(app)
    assert r.json()["models"] == ["qwen3-embedding-0.6b"]
    assert loaded == [EMBED_ALIAS]


async def test_gateway_maps_not_whitelisted_as_non_retryable(specs):
    app = _app(specs, allowed=[EMBED_ALIAS])
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    model = replace(EMBED_MODEL, upstream_name="sd15", alias="local/sd-1.5")
    with pytest.raises(e.ModelNotWhitelisted) as info:
        await _provider(http).embed(model, ["x"], None, {})
    _close(app)
    assert not info.value.retryable


def test_empty_whitelist_allows_everything(specs):
    catalog = RuntimeCatalog(session_factory=None)  # type: ignore[arg-type]
    catalog.set(dict(specs))
    assert len(catalog.specs) == 3 and catalog.rejected == {}


def test_settings_parse_runtime_allowed_models_csv():
    s = get_settings().model_copy()
    parsed = type(s)._split_origins(" local/a , local/b ,,")  # type: ignore[attr-defined]
    assert parsed == ["local/a", "local/b"]
