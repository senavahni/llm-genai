import json

import httpx2
import pytest

from app.schemas.unified import UnifiedChatRequest
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.translate import anthropic_map as am
from app.utils import errors as e
from tests.unit.providers.conftest import (
    json_response,
    model_cfg,
    provider_cfg,
    sse_body,
    sse_response,
)
from tests.unit.providers.fixtures import multi_turn_request

MODEL = model_cfg("anthropic", "claude-test", max_output_tokens=2048)


def _req(messages, **kw) -> UnifiedChatRequest:
    return UnifiedChatRequest.model_validate({"messages": messages, **kw})


# ------------------------------------------------------------------ translator
def test_multiple_system_merged_and_same_roles_merged():
    system, msgs = am.build_messages(
        _req(
            [
                {"role": "system", "content": "A"},
                {"role": "user", "content": "1"},
                {"role": "developer", "content": "B"},
                {"role": "user", "content": "2"},
                {"role": "assistant", "content": "x"},
                {"role": "assistant", "content": "y"},
            ]
        ).messages
    )
    assert system == "A\n\nB"
    assert msgs == [
        {"role": "user", "content": [{"type": "text", "text": "1"}, {"type": "text", "text": "2"}]},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "x"}, {"type": "text", "text": "y"}],
        },
    ]


def test_base64_and_url_images():
    _, msgs = am.build_messages(
        _req(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "lihat"},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
                        {"type": "image_url", "image_url": {"url": "https://x.test/a.png"}},
                    ],
                }
            ]
        ).messages
    )
    blocks = msgs[0]["content"]
    assert blocks[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }
    assert blocks[2] == {"type": "image", "source": {"type": "url", "url": "https://x.test/a.png"}}


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("auto", {"type": "auto"}),
        ("required", {"type": "any"}),
        ("none", {"type": "none"}),
        (
            {"type": "function", "function": {"name": "get_time"}},
            {"type": "tool", "name": "get_time"},
        ),
        (None, None),
    ],
)
def test_tool_choice_variants(choice, expected):
    assert am.map_tool_choice(choice) == expected


def test_multi_turn_parallel_tools_payload():
    built = am.build_payload(MODEL, multi_turn_request())
    p = built.payload
    assert p["system"] == "Kamu asisten.\n\nJawab singkat."
    assert p["max_tokens"] == 2048  # wajib Anthropic: dari max_output_tokens model
    assert [m["role"] for m in p["messages"]] == ["user", "assistant", "user"]
    tool_uses = p["messages"][1]["content"]
    assert [b["type"] for b in tool_uses] == ["tool_use", "tool_use"]
    assert tool_uses[0] == {
        "type": "tool_use",
        "id": "call_a",
        "name": "get_weather",
        "input": {"city": "Bandung"},
    }
    results = p["messages"][2]["content"]  # 2 tool result digabung dalam satu user message
    assert results == [
        {"type": "tool_result", "tool_use_id": "call_a", "content": '{"temp":24}'},
        {"type": "tool_result", "tool_use_id": "call_b", "content": "10:00"},
    ]
    assert p["tools"][0]["name"] == "get_weather"
    assert p["tools"][0]["input_schema"]["required"] == ["city"]
    assert "description" not in p["tools"][1]
    assert p["tool_choice"] == {"type": "auto"}
    assert "temperature" not in p and "stop_sequences" not in p


def test_payload_optional_fields_and_prefill():
    model = model_cfg("anthropic", "c", config={"json_mode_strategy": "prefill"})
    built = am.build_payload(
        model,
        _req(
            [{"role": "user", "content": "json"}],
            stop=["X"],
            temperature=0.1,
            response_format={"type": "json_object"},
            provider_options={
                "thinking": {"type": "enabled", "budget_tokens": 1024},
                "include_reasoning": True,
            },
        ),
    )
    p = built.payload
    assert p["max_tokens"] == am.DEFAULT_MAX_TOKENS
    assert p["stop_sequences"] == ["X"] and p["temperature"] == 0.1
    assert p["thinking"]["budget_tokens"] == 1024 and "include_reasoning" not in p
    assert p["messages"][-1] == {"role": "assistant", "content": "{"}
    assert built.prefill == "{"


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("tool_use", "tool_calls"),
        ("stop_sequence", "stop"),
    ],
)
def test_stop_reason_mapping(reason, expected):
    assert am.parse_response({"content": [], "stop_reason": reason}).finish_reason == expected


def test_parse_response_tools_thinking_usage():
    data = {
        "id": "msg_1",
        "model": "claude-test",
        "stop_reason": "tool_use",
        "content": [
            {"type": "thinking", "thinking": "hmm", "signature": "s"},
            {"type": "text", "text": "Sebentar."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_weather",
                "input": {"city": "Bandung"},
            },
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 20,
        },
    }
    resp = am.parse_response(data)
    assert resp.content == "Sebentar." and resp.reasoning_content is None
    assert resp.tool_calls[0].id == "toolu_1"
    assert json.loads(resp.tool_calls[0].function.arguments) == {"city": "Bandung"}
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.cached_tokens) == (
        130,
        5,
        100,
    )
    assert am.parse_response(data, include_reasoning=True).reasoning_content == "hmm"


STREAM_EVENTS = [
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1},
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Cek"}},
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "toolu_a", "name": "get_weather", "input": {}},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"city": '},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '"Bandung"}'},
    },
    {"type": "content_block_stop", "index": 1},
    {
        "type": "content_block_start",
        "index": 2,
        "content_block": {"type": "tool_use", "id": "toolu_b", "name": "get_time", "input": {}},
    },
    {
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "input_json_delta", "partial_json": "{}"},
    },
    {"type": "content_block_stop", "index": 2},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {"output_tokens": 30},
    },
    {"type": "message_stop"},
]


def _collect_tool_calls(chunks):
    calls: dict[int, dict] = {}
    for c in chunks:
        for d in c.delta_tool_calls or []:
            call = calls.setdefault(d.index, {"id": None, "name": None, "arguments": ""})
            call["id"] = d.id or call["id"]
            call["name"] = d.name or call["name"]
            call["arguments"] += d.arguments or ""
    return calls


def test_stream_translator_tool_index_and_usage():
    tr = am.StreamTranslator()
    chunks = [c for ev in STREAM_EVENTS for c in tr.feed(ev)]
    assert chunks[0].delta_content == "Cek"
    calls = _collect_tool_calls(chunks)
    # index OpenAI = urutan blok tool_use (0, 1), bukan index blok konten (1, 2)
    assert sorted(calls) == [0, 1]
    assert json.loads(calls[0]["arguments"]) == {"city": "Bandung"}  # JSON valid setelah digabung
    assert calls[1]["name"] == "get_time" and json.loads(calls[1]["arguments"]) == {}
    final = chunks[-1]
    assert final.finish_reason == "tool_calls"
    assert (final.usage.prompt_tokens, final.usage.completion_tokens) == (12, 30)


def test_stream_error_event_raises_retryable():
    tr = am.StreamTranslator()
    with pytest.raises(e.UpstreamError) as info:
        tr.feed({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    assert info.value.retryable


# ------------------------------------------------------------------- provider
def _provider(http, settings) -> AnthropicProvider:
    return AnthropicProvider(provider_cfg("anthropic", key_env="ANTHROPIC_API_KEY"), http, settings)


async def test_provider_chat(mock_http, settings):
    http, rec = mock_http(
        lambda r: json_response(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "Halo"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 1},
            }
        )
    )
    resp = await _provider(http, settings).chat(MODEL, multi_turn_request())
    req = rec.requests[-1]
    assert req.url.path == "/v1/messages"
    # SDK anthropic 2.x mengirim key lewat `authorization`; versi lama lewat `x-api-key`
    auth = req.headers.get("x-api-key") or req.headers.get("authorization", "")
    assert "sk-ant-test-000000" in auth
    sent = rec.last_json
    assert sent["max_tokens"] == 2048 and sent["system"].startswith("Kamu")
    assert resp.content == "Halo" and resp.finish_reason == "stop"


async def test_provider_stream(mock_http, settings):
    body = sse_body(*STREAM_EVENTS, event_names=[ev["type"] for ev in STREAM_EVENTS])
    http, rec = mock_http(lambda r: sse_response(body))
    chunks = [c async for c in _provider(http, settings).chat_stream(MODEL, multi_turn_request())]
    assert rec.last_json["stream"] is True
    calls = _collect_tool_calls(chunks)
    assert json.loads(calls[0]["arguments"]) == {"city": "Bandung"}
    assert chunks[-1].usage.completion_tokens == 30


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, e.UpstreamRateLimited),
        (500, e.UpstreamError),
        (529, e.UpstreamError),
        (400, e.UpstreamBadRequest),
    ],
)
async def test_provider_error_mapping(mock_http, settings, status, expected):
    http, _ = mock_http(
        lambda r: httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": f"m{status}"}}
        )
    )
    with pytest.raises(e.GatewayError) as info:
        await _provider(http, settings).chat(MODEL, multi_turn_request())
    assert type(info.value) is expected


async def test_provider_timeout(mock_http, settings):
    def timeout(r):
        raise httpx2.ReadTimeout("slow", request=r)

    http, _ = mock_http(timeout)
    with pytest.raises(e.UpstreamTimeout):
        await _provider(http, settings).chat(MODEL, multi_turn_request())


async def test_embeddings_not_supported(mock_http, settings):
    http, _ = mock_http(lambda r: json_response({}))
    with pytest.raises(e.CapabilityNotSupported):
        await _provider(http, settings).embed(MODEL, ["x"], None, {})
