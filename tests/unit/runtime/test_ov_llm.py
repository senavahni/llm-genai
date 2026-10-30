import asyncio
import base64
import io
import json
import time

import pytest
from PIL import Image

from app.utils.errors import (
    CapabilityNotSupported,
    ContextLengthExceeded,
    InvalidRequestError,
    ModelLoadFailed,
    UnsupportedParameter,
)
from runtime.backends import ov_common, ov_llm_backend, ov_vlm_backend
from runtime.backends.ov_llm_backend import OVLLMBackend
from runtime.backends.ov_vlm_backend import OVVLMBackend
from runtime.core.catalog import LocalModelSpec
from tests.fakes import fake_genai

FIM_CFG = {
    "fim_template": "<P>{prefix}<S>{suffix}<M>",
    "fim_stop": ["<|endoftext|>", "<|fim_pad|>"],
}
TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}


@pytest.fixture
def fake(monkeypatch):
    for mod in (ov_llm_backend, ov_vlm_backend):
        monkeypatch.setattr(mod, "genai", fake_genai.module)
    fake_genai.LLMPipeline.output = "Halo dunia"
    fake_genai.LLMPipeline.token_delay_s = 0.0
    ov_common._verified.clear()
    return fake_genai


@pytest.fixture
def make(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "openvino_model.xml").write_text("x")

    async def _make(
        cls=OVLLMBackend, *, device="gpu", ov_device=None, tools=True, fim=False, **config
    ):
        spec = LocalModelSpec(
            alias="local/qwen",
            upstream_name="qwen",
            device=device,
            runtime_backend=cls.kind,
            artifact_path=str(tmp_path / "m"),
            supports_tools=tools,
            supports_fim=fim,
            supports_vision=cls is OVVLMBackend,
            max_output_tokens=64,
            config={
                "device": ov_device or device.upper(),
                "cache_dir": str(tmp_path / "cache"),
                **config,
            },
        )
        backend = cls(spec)
        await backend.load()
        return backend

    return _make


def _chat(text="Hai", **kw):
    return {"messages": [{"role": "user", "content": text}], **kw}


def _last_call(fake):
    return fake.LLMPipeline.instances[-1].calls[-1]


# ------------------------------------------------------------------ load
async def test_load_npu_properties_and_device(fake, make):
    b = await make(device="npu", max_prompt_len=512, min_response_len=64, prefill_chunk_size=128)
    pipe = fake.LLMPipeline.instances[-1]
    assert pipe.device == "NPU" and b.actual_device() == "npu"
    assert pipe.props["MAX_PROMPT_LEN"] == 512 and pipe.props["MIN_RESPONSE_LEN"] == 64
    assert pipe.props["NPUW_LLM_PREFILL_CHUNK_SIZE"] == 128 and "CACHE_DIR" in pipe.props
    g = await make(device="gpu")
    assert "MAX_PROMPT_LEN" not in fake.LLMPipeline.instances[-1].props
    assert g.actual_device() == "gpu"


@pytest.mark.parametrize("device", ["CPU", "AUTO", "HETERO:GPU,CPU", "MULTI:GPU,CPU"])
async def test_cpu_like_devices_rejected(fake, make, device):
    with pytest.raises(ModelLoadFailed, match="GPU/NPU"):
        await make(device="gpu", ov_device=device)


# ---------------------------------------------------------- config mapping
async def test_generation_config_only_sent_fields(fake, make):
    b = await make()
    await b.chat(_chat())
    cfg = _last_call(fake)["config"]
    assert cfg.max_new_tokens == 64  # models.max_output_tokens
    assert cfg.do_sample is False and cfg.temperature == 1.0  # default model tidak diubah
    assert cfg.apply_chat_template is False and cfg.structured_output_config is None
    await b.chat(
        _chat(
            temperature=0.7,
            top_p=0.9,
            seed=5,
            max_tokens=10,
            stop=["\n\n", "<|fim_pad|>"],
            presence_penalty=0.5,
            provider_options={"top_k": 20, "repetition_penalty": 1.1, "evil": 1},
        )
    )
    cfg = _last_call(fake)["config"]
    assert (cfg.temperature, cfg.do_sample, cfg.top_p, cfg.rng_seed) == (0.7, True, 0.9, 5)
    assert cfg.max_new_tokens == 10 and cfg.presence_penalty == 0.5
    assert (cfg.top_k, cfg.repetition_penalty) == (20, 1.1) and not hasattr(cfg, "evil")
    assert cfg.stop_strings == {"\n\n", "<|fim_pad|>"}
    assert fake.SPECIAL["<|fim_pad|>"] in cfg.stop_token_ids  # stop satu token juga di level token
    await b.chat(_chat(temperature=0))
    assert _last_call(fake)["config"].do_sample is False


async def test_json_mode_uses_structured_output(fake, make):
    b = await make()
    await b.chat(_chat(response_format={"type": "json_object"}))
    so = _last_call(fake)["config"].structured_output_config
    assert json.loads(so.json_schema) == {"type": "object"}
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    await b.chat(_chat(response_format={"type": "json_schema", "json_schema": {"schema": schema}}))
    assert json.loads(_last_call(fake)["config"].structured_output_config.json_schema) == schema
    with pytest.raises(UnsupportedParameter):
        await b.chat(_chat(response_format={"type": "xml"}))
    with pytest.raises(InvalidRequestError):
        await b.chat(_chat(response_format={"type": "json_schema", "json_schema": {}}))


async def test_invalid_requests(fake, make):
    b = await make(tools=False)
    with pytest.raises(UnsupportedParameter):
        await b.chat(_chat(n=2))
    with pytest.raises(InvalidRequestError):
        await b.chat({"messages": []})
    with pytest.raises(CapabilityNotSupported):
        await b.chat(_chat(tools=[TOOL]))
    with pytest.raises(CapabilityNotSupported):
        await b.chat(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,AA=="},
                            }
                        ],
                    }
                ]
            }
        )


# ------------------------------------------------------------- chat & tools
async def test_chat_response_and_usage(fake, make):
    b = await make()
    resp = await b.chat(_chat("Hai", max_tokens=4))
    choice = resp["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "Halo"}
    assert choice["finish_reason"] == "length" and resp["object"] == "chat.completion"
    assert resp["usage"]["completion_tokens"] == 4 and resp["usage"]["prompt_tokens"] > 0


async def test_tool_call_parsed_and_history_rendered(fake, make):
    fake.LLMPipeline.output = (
        '<tool_call>{"name": "get_weather", "arguments": {"city": "Bandung"}}</tool_call>'
    )
    b = await make()
    resp = await b.chat(_chat("Cuaca?", tools=[TOOL], max_tokens=200))
    choice = resp["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and choice["message"]["content"] is None
    call = choice["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"city": "Bandung"}
    history = [
        {"role": "developer", "content": "sistem"},
        {"role": "user", "content": "Cuaca?"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": call["id"], "content": "22C"},
    ]
    fake.LLMPipeline.output = "Suhu 22C"
    resp = await b.chat({"messages": history, "tools": [TOOL]})
    rendered = fake.LLMPipeline.instances[-1].tokenizer.last_history
    assert rendered[0]["role"] == "system"
    # arguments string JSON → objek agar template Qwen merender JSON asli
    assert rendered[2]["tool_calls"][0]["function"]["arguments"] == {"city": "Bandung"}
    assert rendered[3]["tool_call_id"] == call["id"]
    assert resp["choices"][0]["message"]["content"] == "Suhu 22C"
    with pytest.raises(UnsupportedParameter):
        await b.chat(_chat(tools=[TOOL], tool_choice="required"))
    await b.chat(_chat(tools=[TOOL], tool_choice="none"))
    assert fake.LLMPipeline.instances[-1].tokenizer.last_tools is None


# ------------------------------------------------------------------- stream
async def _collect(agen):
    return [c async for c in agen]


async def test_stream_chunks_role_content_usage(fake, make):
    b = await make()
    chunks = await _collect(b.chat_stream(_chat(), asyncio.Event()))
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert text == "Halo dunia"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["usage"]["completion_tokens"] == len("Halo dunia")


async def test_stream_tool_call_buffered_until_closed(fake, make):
    fake.LLMPipeline.output = (
        'Sebentar. <tool_call>{"name": "get_weather", "arguments": {"city": "Bogor"}}</tool_call>'
    )
    b = await make()
    chunks = await _collect(b.chat_stream(_chat(tools=[TOOL], max_tokens=200), asyncio.Event()))
    deltas = [c["choices"][0]["delta"] for c in chunks]
    content = "".join(d.get("content") or "" for d in deltas)
    calls = [tc for d in deltas for tc in d.get("tool_calls") or []]
    assert content == "Sebentar. " and "<tool" not in content
    assert len(calls) == 1 and calls[0]["index"] == 0
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Bogor"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


async def test_stream_multi_token_stop_never_leaks(fake, make):
    fake.LLMPipeline.output = "baris satu\nSTOPbaris dua"
    b = await make()
    chunks = await _collect(b.chat_stream(_chat(stop=["\nSTOP"]), asyncio.Event()))
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert text == "baris satu"


async def test_stream_cancel_stops_generation(fake, make):
    fake.LLMPipeline.output = "x" * 200
    fake.LLMPipeline.token_delay_s = 0.01
    b = await make()
    cancel = asyncio.Event()
    chunks = []
    start = time.perf_counter()
    async for chunk in b.chat_stream(_chat(max_tokens=500), cancel):
        chunks.append(chunk)
        if len(chunks) == 3:
            cancel.set()
    assert chunks[-1]["choices"][0]["finish_reason"] == "cancelled"
    assert fake.LLMPipeline.instances[-1].tokens_generated < 20  # bukan 200 token
    assert time.perf_counter() - start < 0.5


async def test_stream_aclose_stops_thread(fake, make):
    fake.LLMPipeline.output = "y" * 300
    fake.LLMPipeline.token_delay_s = 0.01
    b = await make()
    stream = b.chat_stream(_chat(max_tokens=500), asyncio.Event())
    await stream.__anext__()
    await stream.aclose()  # client putus: generator ditutup → thread berhenti
    assert fake.LLMPipeline.instances[-1].tokens_generated < 30


# --------------------------------------------------------------- completion
async def test_fim_prompt_stop_tokens_and_cleanup(fake, make):
    fake.LLMPipeline.output = "    return n > 1<|fim_pad|>sisa"
    b = await make(device="npu", fim=True, max_prompt_len=512, **FIM_CFG)
    resp = await b.completion({"prompt": "def f(n):\n", "suffix": "\nprint(f(2))"})
    assert resp["choices"][0]["text"] == "    return n > 1"
    call = _last_call(fake)
    assert call["inputs"] == "<P>def f(n):\n<S>\nprint(f(2))<M>"
    cfg = call["config"]
    # stop FIM satu token: hanya di level token (stop_strings menahan stream 1 token)
    assert cfg.stop_strings == set() and fake.SPECIAL["<|fim_pad|>"] in cfg.stop_token_ids
    assert cfg.max_new_tokens == 128  # default FIM
    chunks = await _collect(
        b.completion_stream({"prompt": "def f(n):\n", "suffix": "x"}, asyncio.Event())
    )
    assert "".join(c["choices"][0]["text"] for c in chunks) == "    return n > 1"


async def test_fim_truncates_far_from_cursor(fake, make):
    b = await make(device="npu", fim=True, max_prompt_len=512, fim_max_prompt_tokens=60, **FIM_CFG)
    prefix = "".join(f"a{i:03d}\n" for i in range(100))  # 500 karakter = 500 token palsu
    suffix = "".join(f"z{i:03d}\n" for i in range(100))
    resp = await b.completion({"prompt": prefix, "suffix": suffix, "max_tokens": 4})
    prompt = _last_call(fake)["inputs"]
    assert len(prompt) <= 60
    kept_prefix = prompt.split("<S>")[0].removeprefix("<P>")
    kept_suffix = prompt.split("<S>")[1].removesuffix("<M>")
    assert prefix.endswith(kept_prefix) and suffix.startswith(kept_suffix)  # dekat kursor
    assert kept_prefix and kept_suffix
    assert resp["_warnings"] == ["fim_prompt_truncated"]


async def test_completion_errors_and_npu_limits(fake, make):
    b = await make(device="npu", fim=False, max_prompt_len=50, min_response_len=20)
    with pytest.raises(CapabilityNotSupported):
        await b.completion({"prompt": "x", "suffix": "y"})
    with pytest.raises(UnsupportedParameter):
        await b.completion({"prompt": "x", "echo": True})
    with pytest.raises(InvalidRequestError):
        await b.completion({"prompt": ["a", "b"]})
    with pytest.raises(ContextLengthExceeded):
        await b.chat(_chat("x" * 200))
    resp = await b.completion({"prompt": "y" * 40, "max_tokens": 100})
    # kapasitas KV NPU = 50 + 20 − 40 = 30 token
    assert _last_call(fake)["config"].max_new_tokens == 30
    assert resp["_warnings"] == ["max_tokens_clamped_to_npu_capacity"]


# ------------------------------------------------------------------- vision
def _data_url(size=(2000, 1000)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def test_vlm_images_tagged_resized_and_limited(fake, make):
    b = await make(OVVLMBackend, tools=False, max_image_px=500, max_images=2)
    fake.LLMPipeline.output = "kotak merah"
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Apa ini? "},
            {"type": "image_url", "image_url": {"url": _data_url()}},
            {"type": "text", "text": " dan "},
            {"type": "image_url", "image_url": {"url": _data_url((50, 50))}},
        ],
    }
    resp = await b.chat({"messages": [msg]})
    assert resp["choices"][0]["message"]["content"] == "kotak merah"
    pipe = fake.LLMPipeline.instances[-1]
    assert [t.shape for t in pipe.last_images] == [(1, 250, 500, 3), (1, 50, 50, 3)]
    assert pipe.calls[-1]["config"].apply_chat_template is True
    assert "<ov_genai_image_0>" in pipe.calls[-1]["inputs"]
    assert "<ov_genai_image_1>" in pipe.calls[-1]["inputs"]
    with pytest.raises(InvalidRequestError, match="Maksimal 2"):
        await b.chat({"messages": [{"role": "user", "content": [msg["content"][1]] * 3}]})
    with pytest.raises(CapabilityNotSupported):
        await b.chat({**_chat(), "tools": [TOOL]})
    with pytest.raises(CapabilityNotSupported):
        await b.completion({"prompt": "x"})


async def test_vlm_tools_rendered_hermes_and_parsed(fake, make):
    """Qwen2-VL: template tanpa bagian tools → definisi & riwayat tool dirender Hermes manual."""
    b = await make(OVVLMBackend)
    fake.LLMPipeline.output = (
        '<tool_call>{"name": "get_weather", "arguments": {"city": "Bandung"}}</tool_call>'
    )
    resp = await b.chat(_chat("Cuaca Bandung?", tools=[TOOL], max_tokens=200))
    choice = resp["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"city": "Bandung"}
    system = fake.LLMPipeline.instances[-1].last_history[0]
    assert system["role"] == "system" and "<tools>" in system["content"]
    assert '"name": "get_weather"' in system["content"]

    # giliran kedua: tool call + hasil tool → teks Hermes, role hanya system/user/assistant
    fake.LLMPipeline.output = "Bandung 21C, hujan"
    history = [
        {"role": "system", "content": "Asisten cuaca."},
        {"role": "user", "content": "Cuaca Bandung?"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": call["id"], "content": '{"suhu": 21}'},
        {"role": "tool", "tool_call_id": "x", "content": '{"cuaca": "hujan"}'},
    ]
    resp = await b.chat({"messages": history, "tools": [TOOL]})
    assert resp["choices"][0]["message"]["content"] == "Bandung 21C, hujan"
    rendered = fake.LLMPipeline.instances[-1].last_history
    assert [m["role"] for m in rendered] == ["system", "user", "assistant", "user"]
    assert (
        rendered[0]["content"].startswith("Asisten cuaca.") and "<tools>" in rendered[0]["content"]
    )
    assert (
        '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Bandung"}}'
        in (rendered[2]["content"])
    )
    assert rendered[3]["content"].count("<tool_response>") == 2  # hasil tool digabung

    # stream: blok tool call ditahan sampai lengkap, lalu dikirim sebagai tool_calls
    fake.LLMPipeline.output = (
        'Cek dulu. <tool_call>{"name": "get_weather", "arguments": {"city": "Bogor"}}</tool_call>'
    )
    chunks = await _collect(b.chat_stream(_chat(tools=[TOOL], max_tokens=200), asyncio.Event()))
    calls = [tc for c in chunks for tc in c["choices"][0]["delta"].get("tool_calls") or []]
    assert len(calls) == 1 and chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    with pytest.raises(UnsupportedParameter):
        await b.chat(_chat(tools=[TOOL], tool_choice="required"))
