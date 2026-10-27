import base64
import json

import httpx2
import pytest

from app.schemas.unified import UnifiedChatRequest
from app.services.providers.gemini_provider import GeminiProvider
from app.services.providers.translate import gemini_map as gm
from app.utils import errors as e
from tests.unit.providers.conftest import json_response, model_cfg, provider_cfg, sse_response
from tests.unit.providers.fixtures import multi_turn_request

MODEL = model_cfg("gemini", "gemini-test")


def _req(messages, **kw) -> UnifiedChatRequest:
    return UnifiedChatRequest.model_validate({"messages": messages, **kw})


# ------------------------------------------------------------------ translator
def test_system_instruction_roles_and_merge():
    contents, config = gm.build_request(
        MODEL,
        _req(
            [
                {"role": "system", "content": "A"},
                {"role": "system", "content": "B"},
                {"role": "user", "content": "1"},
                {"role": "user", "content": "2"},
                {"role": "assistant", "content": "x"},
            ],
            temperature=0.3,
            max_tokens=99,
            stop=["S"],
            seed=7,
        ),
    )
    assert config == {
        "system_instruction": "A\n\nB",
        "temperature": 0.3,
        "max_output_tokens": 99,
        "stop_sequences": ["S"],
        "seed": 7,
    }
    assert contents == [
        {"role": "user", "parts": [{"text": "1"}, {"text": "2"}]},
        {"role": "model", "parts": [{"text": "x"}]},
    ]


def test_base64_image_inline_data():
    contents, _ = gm.build_request(
        MODEL,
        _req(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
                    ],
                }
            ]
        ),
    )
    assert contents[0]["parts"][0] == {"inline_data": {"mime_type": "image/png", "data": b"ABC"}}


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("auto", {"mode": "AUTO"}),
        ("required", {"mode": "ANY"}),
        ("none", {"mode": "NONE"}),
        (
            {"type": "function", "function": {"name": "get_time"}},
            {"mode": "ANY", "allowed_function_names": ["get_time"]},
        ),
    ],
)
def test_tool_choice_variants(choice, expected):
    assert gm.map_tool_config(choice) == {"function_calling_config": expected}


def test_multi_turn_parallel_tools_and_schema_cleaning():
    contents, config = gm.build_request(MODEL, multi_turn_request())
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    calls = contents[1]["parts"]
    assert calls == [
        {"function_call": {"name": "get_weather", "args": {"city": "Bandung"}}},
        {"function_call": {"name": "get_time", "args": {"tz": "Asia/Jakarta"}}},
    ]
    # nama function_response diambil dari pemetaan tool_call_id → name riwayat sebelumnya
    assert contents[2]["parts"] == [
        {"function_response": {"name": "get_weather", "response": {"temp": 24}}},
        {"function_response": {"name": "get_time", "response": {"result": "10:00"}}},
    ]
    decl = config["tools"][0]["function_declarations"][0]
    assert "$schema" not in decl["parameters_json_schema"]
    assert config["tool_config"] == {"function_calling_config": {"mode": "AUTO"}}


def test_thought_signature_roundtrip_via_tool_call_id():
    sig = base64.b64encode(b"\x01\x02sig").decode()
    resp = gm.parse_response(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "function_call": {"name": "get_weather", "args": {"city": "X"}},
                                "thought_signature": sig,
                            }
                        ],
                    },
                    "finish_reason": "STOP",
                }
            ]
        }
    )
    call_id = resp.tool_calls[0].id
    assert call_id.startswith("call_") and call_id.endswith(sig)
    contents, _ = gm.build_request(MODEL, multi_turn_request((call_id, "call_other")))
    assert contents[1]["parts"][0]["thought_signature"] == b"\x01\x02sig"
    assert contents[2]["parts"][0]["function_response"]["name"] == "get_weather"


def test_json_mode_and_schema():
    _, config = gm.build_request(
        MODEL,
        _req(
            [{"role": "user", "content": "x"}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "s", "schema": {"$schema": "x", "type": "object"}},
            },
        ),
    )
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == {"type": "object"}


@pytest.mark.parametrize(
    ("reason", "has_tools", "expected"),
    [
        ("STOP", False, "stop"),
        ("MAX_TOKENS", False, "length"),
        ("SAFETY", False, "content_filter"),
        ("RECITATION", False, "content_filter"),
        ("BLOCKLIST", False, "content_filter"),
        ("STOP", True, "tool_calls"),
    ],
)
def test_finish_mapping(reason, has_tools, expected):
    assert gm.map_finish(reason, has_tools) == expected


def test_parse_response_usage_thoughts():
    resp = gm.parse_response(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": "mikir", "thought": True}, {"text": "Halo"}],
                    },
                    "finish_reason": "STOP",
                }
            ],
            "usage_metadata": {
                "prompt_token_count": 10,
                "candidates_token_count": 4,
                "thoughts_token_count": 6,
                "cached_content_token_count": 2,
            },
            "model_version": "gemini-test-001",
        }
    )
    assert resp.content == "Halo" and resp.reasoning_content is None
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.cached_tokens) == (
        10,
        10,
        2,
    )
    assert resp.upstream_model == "gemini-test-001"


# ------------------------------------------------------------------- provider
def _provider(http, settings) -> GeminiProvider:
    return GeminiProvider(provider_cfg("gemini", key_env="GEMINI_API_KEY"), http, settings)


GEN_OK = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {"functionCall": {"name": "get_weather", "args": {"city": "Bandung"}}},
                    {"functionCall": {"name": "get_time", "args": {}}},
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3},
    "modelVersion": "gemini-test",
}


async def test_provider_chat_tool_calls(mock_http, settings):
    http, rec = mock_http(lambda r: json_response(GEN_OK))
    resp = await _provider(http, settings).chat(MODEL, multi_turn_request())
    req = rec.requests[-1]
    assert req.url.path.endswith("/models/gemini-test:generateContent")
    sent = rec.last_json
    assert sent["systemInstruction"]["parts"][0]["text"].startswith("Kamu")
    assert len(sent["contents"]) == 3
    assert resp.finish_reason == "tool_calls"
    assert [tc.function.name for tc in resp.tool_calls] == ["get_weather", "get_time"]
    assert len({tc.id for tc in resp.tool_calls}) == 2
    assert resp.usage.prompt_tokens == 7


async def test_provider_stream(mock_http, settings):
    parts = [
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Ha"}]}}]},
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": "get_time", "args": {"tz": "UTC"}}}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
        },
    ]
    body = "".join(f"data: {json.dumps(p)}\r\n\r\n" for p in parts).encode()
    http, rec = mock_http(lambda r: sse_response(body))
    chunks = [c async for c in _provider(http, settings).chat_stream(MODEL, multi_turn_request())]
    assert "streamGenerateContent" in rec.requests[-1].url.path
    assert chunks[0].delta_content == "Ha"
    tc = chunks[1].delta_tool_calls[0]
    assert tc.index == 0 and tc.name == "get_time" and json.loads(tc.arguments) == {"tz": "UTC"}
    assert chunks[-1].finish_reason == "tool_calls"
    assert chunks[-1].usage.prompt_tokens == 5


async def test_provider_embeddings_estimated_usage(mock_http, settings):
    http, rec = mock_http(
        lambda r: json_response({"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]})
    )
    resp = await _provider(http, settings).embed(
        model_cfg("gemini", "emb"), ["abcd", "efgh"], 2, {}
    )
    assert resp.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert resp.usage.estimated and resp.usage.prompt_tokens == 2
    assert "outputDimensionality" in json.dumps(rec.last_json)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, e.UpstreamRateLimited),
        (500, e.UpstreamError),
        (503, e.UpstreamError),
        (400, e.UpstreamBadRequest),
    ],
)
async def test_provider_error_mapping(mock_http, settings, status, expected):
    http, _ = mock_http(
        lambda r: httpx2.Response(
            status, json={"error": {"code": status, "message": "m", "status": "X"}}
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
