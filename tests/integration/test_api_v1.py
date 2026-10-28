"""TASK-14: endpoint publik /v1 (OpenAI-compatible) end-to-end dengan DB nyata & provider palsu,
termasuk uji kompatibilitas SDK `openai` resmi."""

import base64
import importlib.util
import io
import json
import struct
import uuid
from pathlib import Path

import httpx
import httpx2
import openai
import pytest
import yaml
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings, load_settings
from app.core.database import SessionLocal
from app.core.registry import ProviderRegistry
from app.main import create_app
from app.models import Project, Request, RequestAttempt
from app.models.image import GeneratedImage
from app.models.project import ProjectAllowedModel
from app.schemas.unified import RuntimeMeta
from app.services.key_service import key_service
from app.services.router_service import Router
from app.utils.errors import UpstreamError
from app.utils.streaming import drain_finishers
from tests.fakes.fake_provider import FakeProvider

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
GPU_META = RuntimeMeta(device="gpu", backend="openvino_llm", load_ms=0, queue_ms=1)


def _manage():
    spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts" / "manage.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


async def _project_key(slug: str, patterns: list[str], **project_kw) -> str:
    async with SessionLocal() as s:
        project = Project(slug=slug, name=slug, **project_kw)
        s.add(project)
        await s.flush()
        s.add_all(ProjectAllowedModel(project_id=project.id, model_pattern=p) for p in patterns)
        await s.commit()
        full_key, _ = await key_service.create_key(s, project_id=project.id, name="k")
    return full_key


class Api:
    def __init__(self, app, providers, key, other_key):
        self.app, self.providers, self.key, self.other_key = app, providers, key, other_key

    def client(self, key: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://gw",
            headers={"Authorization": f"Bearer {key or self.key}"},
            timeout=30,
        )

    def sdk(self) -> openai.AsyncOpenAI:
        http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app))
        return openai.AsyncOpenAI(
            api_key=self.key, base_url="http://gw/v1", http_client=http, max_retries=0
        )


@pytest.fixture
async def api(db, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))
    data = yaml.safe_load((ROOT / "scripts" / "seed_models.yaml").read_text(encoding="utf-8"))
    async with SessionLocal() as s:
        await _manage()._seed(s, data, update_local=False)
    settings = load_settings()
    app = create_app(settings)
    registry = ProviderRegistry(settings, http=httpx2.AsyncClient())
    await registry.load()
    providers = {
        code: FakeProvider(cfg, registry.http, settings)
        for code, cfg in registry.provider_configs.items()
        if code in ("openai", "anthropic", "gemini", "openvino")
    }
    providers["openvino"].runtime_meta = GPU_META
    registry.providers = dict(providers)
    registry.disabled = {}
    app.state.registry = registry
    app.state.router = Router(registry)
    key = await _project_key(
        "agent-a",
        [
            "smart",
            "local",
            "vision",
            "autocomplete",
            "image",
            "embed-default",
            "local/*",
            "anthropic/*",
            "openai/*",
        ],
    )
    other = await _project_key("agent-b", ["local/*", "image"])
    yield Api(app, providers, key, other)
    await drain_finishers()


async def _request_rows():
    async with SessionLocal() as s:
        return (await s.execute(select(Request).order_by(Request.created_at))).scalars().all()


# ------------------------------------------------------------------ chat
async def test_chat_non_stream_shape_headers_and_log(api):
    async with api.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={
                "model": "smart",
                "messages": [{"role": "user", "content": "hai"}],
                "metadata": {"ticket": "T-1"},
            },
            headers={"X-Caller-Task": "ringkas-tiket"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "chat.completion" and body["model"] == "smart"
    assert body["id"] == f"chatcmpl-{r.headers['x-request-id']}"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "Hello!"}
    assert body["usage"] == {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6}
    assert r.headers["x-gateway-model"] == "anthropic/claude-sonnet"
    assert r.headers["x-gateway-provider"] == "anthropic"
    assert r.headers["x-gateway-device"] == "remote" and r.headers["x-gateway-attempts"] == "1"
    [row] = await _request_rows()
    assert (row.status, row.endpoint, row.requested_model) == (
        "success",
        "chat.completions",
        "smart",
    )
    assert row.caller_task == "ringkas-tiket" and row.tags == {"ticket": "T-1"}


async def test_chat_stream_done_and_include_usage(api):  # AC2
    async with api.client() as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "smart",
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "hai"}],
            },
        ) as r:
            assert r.status_code == 200
            assert r.headers["x-gateway-model"] == "anthropic/claude-sonnet"
            lines = [ln async for ln in r.aiter_lines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    events = [json.loads(ln[6:]) for ln in lines[:-1]]
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events if e["choices"])
    assert text == "Hello!"
    usage = events[-1]
    assert usage["choices"] == [] and usage["usage"]["completion_tokens"] == 3
    await drain_finishers()
    [row] = await _request_rows()
    assert row.status == "success" and row.is_stream and row.ttft_ms is not None


async def test_stream_error_after_first_chunk_is_sse_error(api):
    api.providers["anthropic"].mode = "fail_mid"
    async with api.client() as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "smart",
                "stream": True,
                "messages": [{"role": "user", "content": "hai"}],
            },
        ) as r:
            lines = [ln async for ln in r.aiter_lines() if ln.startswith("data: ")]
    assert json.loads(lines[-2][6:])["error"]["code"] == "upstream_error"
    assert api.providers["openai"].calls == 0  # tidak ada fallback setelah chunk pertama
    await drain_finishers()
    [row] = await _request_rows()
    assert row.status == "error"


async def test_fallback_recorded_and_all_failed_502(api):
    api.providers["anthropic"].mode = "fail"
    async with api.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 200 and r.headers["x-gateway-attempts"] == "2"
        api.providers["openai"].mode = "fail"
        api.providers["openvino"].mode = "fail"
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
        )
    assert r.status_code == 502 and r.json()["error"]["code"] == "all_candidates_failed"
    assert r.headers["x-gateway-attempts"] == "3"
    rows = await _request_rows()
    assert [x.status for x in rows] == ["success", "error"]
    async with SessionLocal() as s:
        attempts = (
            (await s.execute(select(RequestAttempt).where(RequestAttempt.request_id == rows[1].id)))
            .scalars()
            .all()
        )
    assert len(attempts) == 3


async def test_validation_errors(api):  # AC4
    async with api.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "n": 2, "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 400 and r.json()["error"]["param"] == "n"
        r = await c.post("/v1/chat/completions", json={"model": "smart", "messages": []})
        assert r.status_code == 400
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "tidak-ada", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 404
    async with api.client(api.other_key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "model_not_allowed"
    assert await _request_rows() == []  # error sebelum resolve tidak membuat baris requests


async def test_unknown_fields_passthrough(api):  # AC5
    async with api.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={
                "model": "local/qwen2.5-7b",
                "top_k": 20,
                "provider_options": {"min_p": 0.1},
                "messages": [{"role": "user", "content": "x"}],
            },
        )
    assert r.status_code == 200
    req = api.providers["openvino"].requests[-1]
    assert req.provider_options == {"top_k": 20, "min_p": 0.1}
    assert r.headers["x-gateway-device"] == "gpu"


async def test_vision_base64_and_url_device_gpu(api):  # AC10
    image_part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    async with api.client() as c:
        for url_part in (
            image_part,
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ):
            r = await c.post(
                "/v1/chat/completions",
                json={
                    "model": "vision",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "apa ini?"}, url_part],
                        }
                    ],
                },
            )
            assert r.status_code == 200, r.text
            assert r.headers["x-gateway-model"] == "local/qwen2-vl-2b"
            assert r.headers["x-gateway-device"] == "gpu"


# ---------------------------------------------------------------- models
async def test_models_filtered_by_project(api):  # AC3
    async with api.client(api.other_key) as c:
        r = await c.get("/v1/models")
    ids = [m["id"] for m in r.json()["data"]]
    assert "image" in ids and "local/qwen2.5-7b" in ids
    assert "smart" not in ids and not any(i.startswith("anthropic/") for i in ids)
    image = next(m for m in r.json()["data"] if m["id"] == "image")
    assert image["owned_by"] == "gateway-route" and image["x_capabilities"]["image_edit"]
    async with api.client(api.other_key) as c:
        r = await c.get("/v1/models/local/qwen2.5-7b")
        assert r.json()["x_device"] == "gpu"
        assert (await c.get("/v1/models/smart")).status_code == 404


# ----------------------------------------------------------- completions
async def test_fim_completion_autocomplete(api):  # AC9
    async with api.client() as c:
        r = await c.post(
            "/v1/completions",
            json={"model": "autocomplete", "prompt": "def f(n):\n", "suffix": "\nprint(f(2))"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["text"] == "    return n > 1"
        assert r.headers["x-gateway-model"] == "local/qwen2.5-coder-1.5b"
        async with c.stream(
            "POST",
            "/v1/completions",
            json={"model": "autocomplete", "prompt": "a", "suffix": "b", "stream": True},
        ) as s:
            lines = [ln async for ln in s.aiter_lines() if ln.startswith("data: ")]
    text = "".join(json.loads(ln[6:])["choices"][0]["text"] for ln in lines[:-1])
    assert text == "    return n > 1" and lines[-1] == "data: [DONE]"
    assert api.providers["openvino"].requests[-1].suffix == "b"


# ------------------------------------------------------------- embeddings
async def test_embeddings_base64_decodable_by_sdk(api):  # AC6
    client = api.sdk()
    resp = await client.embeddings.create(
        model="embed-default", input=["a", "b"], encoding_format="base64"
    )
    raw = (
        base64.b64decode(resp.data[1].embedding)
        if isinstance(resp.data[1].embedding, str)
        else None
    )
    if raw is not None:
        assert list(struct.unpack("<3f", raw)) == [0.5, -1.25, 1.0]
    else:
        assert resp.data[1].embedding == [0.5, -1.25, 1.0]
    floats = await client.embeddings.create(model="embed-default", input="halo")
    assert floats.data[0].embedding == [0.5, -1.25, 0.0]
    assert floats.usage.prompt_tokens == 2


# ----------------------------------------------------------------- images
async def test_images_b64_and_unsupported_size(api):  # AC7
    client = api.sdk()
    resp = await client.images.generate(
        model="image",
        prompt="kucing",
        size="512x512",
        response_format="b64_json",
        n=2,
        extra_body={"seed": 9, "steps": 20},
    )
    png = base64.b64decode(resp.data[0].b64_json)
    assert Image.open(io.BytesIO(png)).format == "PNG" and len(resp.data) == 2
    with pytest.raises(openai.BadRequestError) as info:
        await client.images.generate(model="image", prompt="kucing", size="1024x1024")
    assert info.value.code == "unsupported_size" and "512x512" in info.value.message
    req = api.providers["openvino"].requests[-1]
    assert (req.seed, req.steps) == (9, 20)


async def test_image_url_access_scoped_to_project(api, tmp_path):  # AC8
    async with api.client() as c:
        r = await c.post(
            "/v1/images/generations",
            json={"model": "image", "prompt": "rumah", "response_format": "url"},
        )
        assert r.status_code == 200, r.text
        url = r.json()["data"][0]["url"]
        path = url.removeprefix("http://gw")
        got = await c.get(path)
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert got.headers["cache-control"] == "private, max-age=3600"
    async with api.client(api.other_key) as c:
        r = await c.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "image_not_found"
        r = await c.get(f"/v1/images/files/{uuid.uuid4()}")
        assert r.status_code == 404
    async with SessionLocal() as s:
        [img] = (await s.execute(select(GeneratedImage))).scalars().all()
    assert (tmp_path / "storage" / img.file_path).is_file()
    [row] = await _request_rows()
    assert row.image_count == 1 and row.device == "gpu"


async def test_image_edits_multipart_image_to_image(api):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buf, format="PNG")
    async with api.client() as c:
        r = await c.post(
            "/v1/images/edits",
            files={"image": ("in.png", buf.getvalue(), "image/png")},
            data={
                "prompt": "malam hari",
                "model": "image",
                "response_format": "b64_json",
                "strength": "0.5",
            },
        )
        assert r.status_code == 200, r.text
        req = api.providers["openvino"].requests[-1]
        assert req.image == buf.getvalue() and req.strength == 0.5
        r = await c.post(
            "/v1/images/edits",
            files={
                "image": ("in.png", buf.getvalue(), "image/png"),
                "mask": ("m.png", buf.getvalue(), "image/png"),
            },
            data={"prompt": "x"},
        )
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_parameter"
    rows = await _request_rows()
    assert rows[0].endpoint == "images.edits" and rows[0].status == "success"


# ------------------------------------------------------------------ usage
async def test_usage_endpoint(api):
    async with api.client() as c:
        await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
        )
        r = await c.get("/v1/usage")
    [row] = r.json()["data"]
    assert row["model"] == "anthropic/claude-sonnet" and row["requests"] == 1


# ------------------------------------------------------------ SDK resmi
async def test_openai_sdk_compatibility(api):  # AC1
    client = api.sdk()
    resp = await client.chat.completions.create(
        model="smart", messages=[{"role": "user", "content": "Halo"}], temperature=0.2
    )
    assert resp.choices[0].message.content == "Hello!" and resp.usage.total_tokens == 6
    stream = await client.chat.completions.create(
        model="smart",
        messages=[{"role": "user", "content": "Halo"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    parts, usage = [], None
    async for chunk in stream:
        if chunk.choices:
            parts.append(chunk.choices[0].delta.content or "")
        if chunk.usage:
            usage = chunk.usage
    assert "".join(parts) == "Hello!" and usage.completion_tokens == 3
    comp = await client.completions.create(model="autocomplete", prompt="def f(n):\n", suffix="\n")
    assert comp.choices[0].text == "    return n > 1"
    models = await client.models.list()
    assert "smart" in [m.id for m in models.data]
    with pytest.raises(openai.NotFoundError):
        await client.chat.completions.create(
            model="tidak-ada", messages=[{"role": "user", "content": "x"}]
        )
    api.providers["anthropic"].mode = "fail"
    api.providers["anthropic"].error = UpstreamError("down")
    resp = await client.chat.completions.with_raw_response.create(
        model="smart", messages=[{"role": "user", "content": "x"}]
    )
    assert resp.headers["x-gateway-attempts"] == "2"
