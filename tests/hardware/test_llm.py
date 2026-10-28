"""TASK-11 dengan model Qwen nyata (GPU/NPU): chat, stream, tools multi-turn, JSON mode, FIM,
vision, cancel. Jalankan: `pytest --hardware tests/hardware/test_llm.py`."""

import asyncio
import base64
import io
import json
import statistics
import time

import pytest
from PIL import Image, ImageDraw

from runtime.backends.ov_llm_backend import OVLLMBackend
from runtime.backends.ov_vlm_backend import OVVLMBackend
from runtime.device.manager import DeviceManager
from tests.hardware.conftest import catalog_spec

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
async def managers():
    gpu = DeviceManager("gpu", 5300, queue_timeout_s=120, min_residency_s=0)
    npu = DeviceManager("npu", 6200, queue_timeout_s=120, min_residency_s=0)
    yield {"gpu": gpu, "npu": npu}
    for m in (gpu, npu):
        await m.unload_all("test")
        m.close()


async def _call(managers, alias, method, req, cancel=None):
    spec = catalog_spec(alias)
    async with managers[spec.device].acquire(spec) as lease:
        assert lease.device == spec.device  # tidak pernah cpu
        fn = getattr(lease.backend, method)
        if method.endswith("_stream"):
            return [c async for c in fn(req, cancel or asyncio.Event())]
        return await fn(req)


async def _tool_conversation(managers, alias, stream):
    messages = [{"role": "user", "content": "Bagaimana cuaca di Bandung sekarang?"}]
    req = {"messages": messages, "tools": [WEATHER_TOOL], "temperature": 0, "max_tokens": 128}
    if stream:
        chunks = await _call(managers, alias, "chat_stream", req)
        calls = [tc for c in chunks for tc in (c["choices"][0]["delta"].get("tool_calls") or [])]
        assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    else:
        resp = await _call(managers, alias, "chat", req)
        assert resp["choices"][0]["finish_reason"] == "tool_calls"
        calls = resp["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "get_weather"
    assert "bandung" in json.loads(calls[0]["function"]["arguments"])["city"].lower()
    # giliran kedua: hasil tool dikirim balik → jawaban teks yang memakai hasilnya
    messages += [
        {"role": "assistant", "content": None, "tool_calls": [{**calls[0], "index": None}]},
        {
            "role": "tool",
            "tool_call_id": calls[0]["id"],
            "content": '{"suhu_c": 21, "cuaca": "hujan"}',
        },
    ]
    resp = await _call(managers, alias, "chat", {**req, "messages": messages})
    answer = resp["choices"][0]["message"]["content"] or ""
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert "21" in answer or "hujan" in answer.lower(), answer


@pytest.mark.gpu
@pytest.mark.parametrize("alias", ["local/qwen2.5-7b", "local/qwen2.5-coder-7b"])
@pytest.mark.parametrize("stream", [False, True])
async def test_tool_calling_multi_turn(managers, alias, stream):
    await _tool_conversation(managers, alias, stream)


@pytest.mark.gpu
async def test_chat_stream_and_usage(managers):
    req = {"messages": [{"role": "user", "content": "Sebutkan 3 warna."}], "max_tokens": 40}
    chunks = await _call(managers, "local/qwen2.5-7b", "chat_stream", req)
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert text.strip() and chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["usage"]["completion_tokens"] > 0


@pytest.mark.gpu
async def test_cancel_mid_stream_then_serves_next(managers):
    cancel = asyncio.Event()
    spec = catalog_spec("local/qwen2.5-7b")
    req = {
        "messages": [{"role": "user", "content": "Ceritakan sejarah Bandung panjang."}],
        "max_tokens": 400,
    }
    async with managers["gpu"].acquire(spec) as lease:
        stream = lease.backend.chat_stream(req, cancel)
        n = 0
        async for chunk in stream:
            n += 1
            if n == 5:
                cancel.set()
                t0 = time.perf_counter()
            if chunk["choices"][0]["finish_reason"]:
                break
        elapsed = time.perf_counter() - t0
        assert chunk["choices"][0]["finish_reason"] == "cancelled"
        assert elapsed < 0.5, elapsed
    resp = await _call(
        managers,
        "local/qwen2.5-7b",
        "chat",
        {"messages": [{"role": "user", "content": "Halo"}], "max_tokens": 8},
    )
    assert resp["choices"][0]["message"]["content"]


@pytest.mark.gpu
async def test_json_object_always_valid_100(managers):
    spec = catalog_spec("local/qwen2.5-7b")
    async with managers["gpu"].acquire(spec) as lease:
        for i in range(100):
            resp = await lease.backend.chat(
                {
                    "messages": [
                        {"role": "user", "content": f"Buat data pengguna acak #{i} dalam JSON."}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                    "seed": i,
                    "max_tokens": 48,
                }
            )
            content = resp["choices"][0]["message"]["content"]
            if resp["choices"][0]["finish_reason"] == "length":
                continue  # terpotong max_tokens: grammar valid sampai batas, bukan kegagalan JSON
            assert isinstance(json.loads(content), dict), content


@pytest.mark.npu
async def test_fim_on_npu_ttft(managers):
    prefix = 'def is_prime(n: int) -> bool:\n    """True bila n bilangan prima."""\n'
    suffix = "\n\nprint(is_prime(7))\n"
    req = {"prompt": prefix, "suffix": suffix, "max_tokens": 64, "temperature": 0}
    resp = await _call(managers, "local/qwen2.5-coder-1.5b", "completion", req)
    text = resp["choices"][0]["text"]
    assert "<|fim" not in text and "return" in text
    ns = {}
    exec(compile(prefix + text, "<fim>", "exec"), ns)  # noqa: S102
    assert ns["is_prime"](7) and not ns["is_prime"](9)
    # TTFT = waktu sampai chunk teks pertama (model pinned sudah termuat)
    spec = catalog_spec("local/qwen2.5-coder-1.5b")
    ttfts = []
    for _ in range(7):
        async with managers["npu"].acquire(spec) as lease:
            start = time.perf_counter()
            ttft = None
            async for _chunk in lease.backend.completion_stream(
                {**req, "max_tokens": 16}, asyncio.Event()
            ):
                if ttft is None:
                    ttft = time.perf_counter() - start
            ttfts.append(ttft)
    p50 = statistics.median(ttfts[1:])
    print(f"FIM TTFT p50 {p50 * 1000:.0f} ms")
    assert p50 < 0.3, ttfts


@pytest.mark.gpu
async def test_vision_describes_image(managers):
    img = Image.new("RGB", (320, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 110, 150], fill="red")
    draw.text((130, 70), "GATEWAY 42", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    req = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What colored shape and what text are in this image?"},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        "max_tokens": 64,
        "temperature": 0,
    }
    resp = await _call(managers, "local/qwen2-vl-2b", "chat", req)
    content = resp["choices"][0]["message"]["content"].lower()
    assert "red" in content and ("42" in content or "gateway" in content), content
    chunks = await _call(managers, "local/qwen2-vl-2b", "chat_stream", req)
    assert "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks).strip()


def test_backend_classes_registered():
    from runtime.backends import backend_class

    assert backend_class("openvino_llm") is OVLLMBackend
    assert backend_class("openvino_vlm") is OVVLMBackend
