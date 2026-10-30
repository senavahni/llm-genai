"""Test hardware end-to-end LEWAT GATEWAY yang sedang berjalan (TASK-20): smoke semua model lokal,
anti-CPU, uji swap NÃ—, dan kontensi GPU+NPU. Butuh gateway (:8000) + runtime (:8100) hidup dan key
client yang boleh memakai `local/*`:

    set LGW_TEST_KEY=lgw_...           (opsional: LGW_BASE_URL, LGW_SWAP_N, default 100)
    scripts\\test-hardware.bat tests\\hardware\\test_gateway_e2e.py

Metrik (memori device, OOM, request per device) dibaca dari /metrics gateway (akses localhost);
cek `device='cpu'` memakai DB dev (DATABASE_URL di .env)."""

import asyncio
import base64
import io
import json
import os
import random
import time
from datetime import UTC, datetime

import httpx
import pytest
from PIL import Image, ImageDraw
from prometheus_client.parser import text_string_to_metric_families

from scripts._seedfile import load_seed, local_models
from tests.conftest import _dotenv

pytestmark = [pytest.mark.gpu, pytest.mark.npu]

BASE_URL = os.environ.get("LGW_BASE_URL", "http://127.0.0.1:8000")
KEY = os.environ.get("LGW_TEST_KEY", "")
CATALOG = {m["alias"]: m for m in local_models(load_seed())}
FIM_ALIAS = next(a for a, m in CATALOG.items() if m.get("supports_fim"))
IMAGE_ALIAS = next(a for a, m in CATALOG.items() if m["model_type"] == "image")
TOOL_MODELS = sorted(a for a, m in CATALOG.items() if m.get("supports_tools"))
STARTED = datetime.now(UTC)
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Ambil cuaca terkini sebuah kota",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


@pytest.fixture(scope="module")
def active() -> set[str]:
    """Model lokal yang aktif di gateway (profil operasional, mis. ram16)."""
    if not KEY:
        pytest.skip("set LGW_TEST_KEY (key client dengan akses local/*)")
    try:
        r = httpx.get(
            f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {KEY}"}, timeout=10
        )
        r.raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"gateway tidak berjalan di {BASE_URL}")
    return {m["id"] for m in r.json()["data"]} & set(CATALOG)


@pytest.fixture(scope="module")
def gw(active):
    return lambda: httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {KEY}"}, timeout=900
    )


def require(active: set[str], *aliases: str) -> None:
    missing = [a for a in aliases if a not in active]
    if missing:
        pytest.skip(f"model nonaktif di profil saat ini: {missing}")


def metrics() -> dict[tuple[str, tuple], float]:
    text = httpx.get(f"{BASE_URL}/metrics", timeout=15).text
    out = {}
    for family in text_string_to_metric_families(text):
        for s in family.samples:
            out[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return out


def metric_sum(snapshot: dict, name: str, **labels: str) -> float:
    return sum(
        v
        for (n, lbl), v in snapshot.items()
        if n == name and all(dict(lbl).get(k) == want for k, want in labels.items())
    )


def png_data_url() -> str:
    img = Image.new("RGB", (256, 128), "white")
    ImageDraw.Draw(img).rectangle([10, 10, 90, 118], fill="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def call_model(
    client: httpx.AsyncClient, alias: str, max_tokens: int = 16, *, fim: bool = False
) -> httpx.Response:
    item = CATALOG[alias]
    if item["model_type"] == "image":
        body = {
            "model": alias,
            "prompt": "a red house",
            "size": "512x512",
            "n": 1,
            "response_format": "b64_json",
        }
        return await client.post("/v1/images/generations", json=body)
    if fim or item["model_type"] == "completion":
        body = {
            "model": alias,
            "prompt": "def add(a, b):\n",
            "suffix": "\n\nprint(add(1, 2))\n",
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        return await client.post("/v1/completions", json=body)
    content: list | str = "Sebutkan satu warna."
    if item.get("supports_vision"):
        content = [
            {"type": "text", "text": "What color is the shape?"},
            {"type": "image_url", "image_url": {"url": png_data_url()}},
        ]
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    return await client.post("/v1/chat/completions", json=body)


async def call_retry_busy(client: httpx.AsyncClient, alias: str, **kw) -> httpx.Response:
    """Model GPU sebelumnya masih dalam min residency (RUNTIME_MIN_RESIDENCY_S) â†’ tunggu."""
    for _ in range(3):
        r = await call_model(client, alias, **kw)
        if r.status_code == 503 and r.json()["error"]["code"] == "model_busy":
            await asyncio.sleep(int(r.headers.get("retry-after", 30)))
            continue
        break
    return r


@pytest.mark.parametrize("alias", sorted(CATALOG))
async def test_smoke_each_local_model(gw, active, alias):
    require(active, alias)
    modes = [False, True] if CATALOG[alias].get("supports_fim") else [False]
    async with gw() as client:
        for fim in modes:  # model chat ber-FIM: chat DAN /v1/completions
            r = await call_retry_busy(client, alias, fim=fim)
            assert r.status_code == 200, r.text
            assert r.headers["x-gateway-device"] == CATALOG[alias]["device"]
            assert r.headers["x-gateway-device"] in {"gpu", "npu"}


def _tool_body(alias: str, messages: list, stream: bool) -> dict:
    return {
        "model": alias,
        "messages": messages,
        "tools": [WEATHER_TOOL],
        "temperature": 0,
        "max_tokens": 160,
        "stream": stream,
    }


async def _tool_turn(client: httpx.AsyncClient, alias: str, messages: list, stream: bool):
    """Satu giliran; kembalikan (finish_reason, content, tool_calls) dari stream atau non-stream."""
    body = _tool_body(alias, messages, stream)
    if not stream:
        r = await client.post("/v1/chat/completions", json=body)
        assert r.status_code == 200, r.text
        choice = r.json()["choices"][0]
        return (
            choice["finish_reason"],
            choice["message"].get("content"),
            choice["message"].get("tool_calls") or [],
        )
    content, calls, finish = "", [], None
    async with client.stream("POST", "/v1/chat/completions", json=body) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if not line.startswith("data: {"):
                continue
            choice = (json.loads(line[6:]).get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            calls += delta.get("tool_calls") or []
            finish = choice.get("finish_reason") or finish
    return finish, content, calls


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("alias", TOOL_MODELS)
async def test_tool_calling_multi_turn(gw, active, alias, stream):
    """Tool calling (dipakai klien MCP): panggil tool â†’ kirim hasil â†’ jawaban teks."""
    require(active, alias)
    messages = [{"role": "user", "content": "Bagaimana cuaca di Bandung sekarang?"}]
    async with gw() as client:
        finish, content, calls = await _tool_turn(client, alias, messages, stream)
        assert finish == "tool_calls", (finish, content)
        assert calls[0]["function"]["name"] == "get_weather"
        args = json.loads(calls[0]["function"]["arguments"])
        assert "bandung" in str(args.get("city", "")).lower(), args
        messages += [
            {"role": "assistant", "content": None, "tool_calls": calls},
            {
                "role": "tool",
                "tool_call_id": calls[0]["id"],
                "content": '{"suhu_c": 21, "cuaca": "hujan"}',
            },
        ]
        finish, content, calls = await _tool_turn(client, alias, messages, stream)
    print(f"\n{alias} stream={stream}: {content!r}")
    assert finish == "stop" and not calls
    assert "21" in content or "hujan" in content.lower(), content


async def test_swap_n_times_without_oom_within_budget(gw, active):
    gpu_chat = [
        a
        for a in sorted(active)
        if CATALOG[a]["device"] == "gpu" and CATALOG[a]["model_type"] == "chat"
    ]
    if len(gpu_chat) < 2:
        pytest.skip(f"uji swap butuh â‰¥ 2 model GPU aktif (profil full); aktif: {gpu_chat}")
    require(active, FIM_ALIAS)
    n = int(os.environ.get("LGW_SWAP_N", "100"))
    before = metrics()
    budget = metric_sum(before, "runtime_device_memory_budget_mb", device="gpu")
    oom_before = metric_sum(before, "runtime_oom_total")
    rng = random.Random(42)
    queue: asyncio.Queue[str] = asyncio.Queue()
    for _ in range(n):
        queue.put_nowait(rng.choice(gpu_chat))
    statuses: list[tuple[str, int, str]] = []
    fim_failures: list[str] = []
    peak = 0.0
    done = asyncio.Event()

    async def worker(client: httpx.AsyncClient) -> None:
        while not queue.empty():
            alias = queue.get_nowait()
            r = await call_model(client, alias, max_tokens=8)
            code = r.json().get("error", {}).get("code", "") if r.status_code != 200 else ""
            statuses.append((alias, r.status_code, code))

    async def autocomplete(client: httpx.AsyncClient) -> None:  # pinned, terus berjalan
        while not done.is_set():
            r = await call_model(client, FIM_ALIAS, max_tokens=8, fim=True)
            if r.status_code != 200:
                fim_failures.append(r.text[:200])

    async def sample_memory() -> None:
        nonlocal peak
        while not done.is_set():
            used = metric_sum(
                await asyncio.to_thread(metrics), "runtime_device_memory_used_mb", device="gpu"
            )
            peak = max(peak, used)
            await asyncio.sleep(1)

    started = time.perf_counter()
    async with gw() as client:
        background = [
            asyncio.create_task(autocomplete(client)),
            asyncio.create_task(sample_memory()),
        ]
        await asyncio.gather(*(worker(client) for _ in range(4)))
        done.set()
        await asyncio.gather(*background)
    elapsed = time.perf_counter() - started

    after = metrics()
    rejected = [s for s in statuses if s[1] != 200]
    print(
        f"\nswap {n}x: {elapsed:.0f} s, ditolak {len(rejected)}, peak GPU {peak:.0f}/{budget:.0f}"
        f" MB, evictions {metric_sum(after, 'runtime_evictions_total', device='gpu'):.0f}"
    )
    assert metric_sum(after, "runtime_oom_total") == oom_before
    assert peak <= budget * 1.03
    assert not fim_failures, fim_failures[:3]
    assert all(code == "model_busy" for _, _, code in rejected), rejected[:5]


async def test_gpu_npu_contention(gw, active):
    """Beban NPU dan GPU bersamaan: keduanya sukses di device masing-masing. Profil penuh: SD
    (NPU) + chat GPU; profil ram16: chat kode Coder-1.5B (NPU) + VL-2B (GPU)."""
    gpu = next(
        (
            a
            for a in sorted(active)
            if CATALOG[a]["device"] == "gpu" and CATALOG[a]["model_type"] == "chat"
        ),
        None,
    )
    npu = IMAGE_ALIAS if IMAGE_ALIAS in active else FIM_ALIAS
    if gpu is None or npu not in active:
        pytest.skip("butuh satu model GPU dan satu model NPU aktif")

    async def timed(alias: str, **kw) -> tuple[int, float, str]:
        async with gw() as client:
            t0 = time.perf_counter()
            r = await call_retry_busy(client, alias, **kw)
            return r.status_code, time.perf_counter() - t0, r.headers.get("x-gateway-device", "")

    (npu_status, npu_s, npu_dev), (gpu_status, gpu_s, gpu_dev) = await asyncio.gather(
        timed(npu, max_tokens=64), timed(gpu, max_tokens=64)
    )
    print(f"\nkontensi: {npu} {npu_s:.1f} s ({npu_dev}), {gpu} {gpu_s:.1f} s ({gpu_dev})")
    assert (npu_status, gpu_status) == (200, 200)
    assert (npu_dev, gpu_dev) == ("npu", "gpu")


async def test_no_local_request_on_cpu(gw):
    """NF9: dijalankan terakhir di modul ini; tidak boleh ada request lokal di device cpu."""
    import asyncpg

    url = (_dotenv.get("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        cpu, local = await conn.fetchrow(
            "SELECT count(*) FILTER (WHERE device = 'cpu'), count(*) FILTER (WHERE device IS "
            "NOT NULL) FROM requests WHERE created_at >= $1",
            STARTED,
        )
    finally:
        await conn.close()
    assert local > 0 and cpu == 0
    assert metric_sum(metrics(), "gateway_requests_by_device_total", device="cpu") == 0
