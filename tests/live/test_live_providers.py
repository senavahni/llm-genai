"""Smoke test provider remote ASLI lewat gateway yang berjalan (manual, memakan kredit API).

    set LGW_TEST_KEY=lgw_...    (key client dengan akses anthropic/*, openai/*, gemini/*)
    scripts\\test.bat tests\\live --live -v

Setiap model remote chat di katalog dipanggil sekali (non-stream + stream), embedding sekali.
Model yang provider-nya nonaktif (key tidak diisi di .env) di-skip. Hasil dicatat manual di
docs/perf-report.md bagian "Live smoke"."""

import os

import httpx
import pytest
import yaml

from tests.conftest import ROOT

pytestmark = pytest.mark.live

BASE_URL = os.environ.get("LGW_BASE_URL", "http://127.0.0.1:8000")
KEY = os.environ.get("LGW_TEST_KEY", "")
_SEED = yaml.safe_load((ROOT / "scripts" / "seed_models.yaml").read_text(encoding="utf-8"))
REMOTE = [m for m in _SEED["models"] if m["provider"] != "openvino"]
CHAT = [m["alias"] for m in REMOTE if m["model_type"] == "chat"]
EMBED = [m["alias"] for m in REMOTE if m["model_type"] == "embedding"]


@pytest.fixture(scope="module")
def client():
    if not KEY:
        pytest.skip("set LGW_TEST_KEY")
    with httpx.Client(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {KEY}"}, timeout=120
    ) as c:
        try:
            available = {m["id"] for m in c.get("/v1/models").raise_for_status().json()["data"]}
        except httpx.HTTPError as exc:
            pytest.skip(f"gateway tidak dapat diakses: {exc}")
        c.available = available  # type: ignore[attr-defined]
        yield c


def _require(client, alias: str) -> None:
    if alias not in client.available:
        pytest.skip(f"{alias} tidak tersedia (provider nonaktif / tidak diizinkan untuk key)")


@pytest.mark.parametrize("alias", CHAT)
def test_chat_non_stream_and_stream(client, alias):
    _require(client, alias)
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": "Balas: OK"}],
        "max_tokens": 16,
    }
    r = client.post("/v1/chat/completions", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["usage"]["total_tokens"] > 0
    assert r.headers["x-gateway-provider"] == alias.split("/")[0]

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={**body, "stream": True, "stream_options": {"include_usage": True}},
    ) as s:
        assert s.status_code == 200
        lines = [line for line in s.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    assert any('"usage"' in line for line in lines)


@pytest.mark.parametrize("alias", EMBED)
def test_embeddings(client, alias):
    _require(client, alias)
    r = client.post("/v1/embeddings", json={"model": alias, "input": ["halo", "dunia"]})
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 2
