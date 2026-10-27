import json

import httpx2
import pytest

from app.schemas.unified import (
    ImagePart,
    ImageURL,
    TextPart,
    ToolDef,
    UnifiedChatRequest,
    UnifiedMessage,
)
from app.services.providers.openai_provider import OpenAIProvider
from app.utils import errors as e
from tests.unit.providers.conftest import (
    json_response,
    model_cfg,
    provider_cfg,
    sse_body,
    sse_response,
)

MODEL = model_cfg("openai", "gpt-test")
CHAT_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-test-2026",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Halo"}}
    ],
    "usage": {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 3},
    },
}


def _provider(http, settings, **cfg) -> OpenAIProvider:
    return OpenAIProvider(provider_cfg("openai", key_env="OPENAI_API_KEY", **cfg), http, settings)


def _req(**kw) -> UnifiedChatRequest:
    return UnifiedChatRequest(messages=[UnifiedMessage(role="user", content="hi")], **kw)


async def test_chat_payload_has_no_none_fields_and_maps_response(mock_http, settings):
    http, rec = mock_http(lambda r: json_response(CHAT_OK))
    resp = await _provider(http, settings).chat(MODEL, _req(temperature=0.2))
    sent = rec.last_json
    assert sent == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.2,
    }
    assert all(v is not None for v in sent.values())
    assert rec.requests[-1].url.path == "/v1/chat/completions"
    assert rec.requests[-1].headers["authorization"] == "Bearer sk-test-openai-000000"
    assert resp.content == "Halo"
    assert resp.finish_reason == "stop"
    assert resp.upstream_model == "gpt-test-2026"
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.cached_tokens) == (
        5,
        2,
        3,
    )


async def test_tools_json_mode_image_and_provider_options_passthrough(mock_http, settings):
    http, rec = mock_http(
        lambda r: json_response(
            {
                **CHAT_OK,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city":"Bdg"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        )
    )
    req = UnifiedChatRequest(
        messages=[
            UnifiedMessage(
                role="user",
                content=[
                    TextPart(text="apa ini?"),
                    ImagePart(image_url=ImageURL(url="data:image/png;base64,AAAA")),
                ],
            )
        ],
        tools=[
            ToolDef.model_validate(
                {
                    "type": "function",
                    "function": {"name": "get_weather", "parameters": {"type": "object"}},
                }
            )
        ],
        tool_choice="auto",
        response_format={"type": "json_object"},
        max_tokens=50,
        provider_options={"reasoning_effort": "low", "include_reasoning": True},
    )
    model = model_cfg("openai", "o-test", config={"max_tokens_param": "max_completion_tokens"})
    resp = await _provider(http, settings).chat(model, req)
    sent = rec.last_json
    assert sent["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }
    assert sent["tools"][0]["function"] == {"name": "get_weather", "parameters": {"type": "object"}}
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_completion_tokens"] == 50 and "max_tokens" not in sent
    assert sent["reasoning_effort"] == "low"
    assert "include_reasoning" not in sent  # opsi khusus gateway tidak diteruskan
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].function.name == "get_weather"
    assert json.loads(resp.tool_calls[0].function.arguments) == {"city": "Bdg"}


async def test_stream_maps_content_tool_calls_and_final_usage(mock_http, settings):
    body = sse_body(
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Ha"}}],
        },
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "f", "arguments": '{"a"'},
                            }
                        ]
                    },
                }
            ],
        },
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ":1}"}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        },
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-test",
            "choices": [],
            "usage": {
                "prompt_tokens": 9,
                "completion_tokens": 4,
                "total_tokens": 13,
                "prompt_tokens_details": {"cached_tokens": 1},
            },
        },
        "[DONE]",
    )
    http, rec = mock_http(lambda r: sse_response(body))
    chunks = [c async for c in _provider(http, settings).chat_stream(MODEL, _req())]
    sent = rec.last_json
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
    assert chunks[0].delta_content == "Ha"
    args = "".join(d.arguments or "" for c in chunks for d in (c.delta_tool_calls or []))
    assert json.loads(args) == {"a": 1}
    assert chunks[1].delta_tool_calls[0].name == "f"
    assert chunks[2].finish_reason == "tool_calls"
    assert chunks[-1].usage.prompt_tokens == 9 and chunks[-1].usage.cached_tokens == 1


async def test_embeddings(mock_http, settings):
    http, rec = mock_http(
        lambda r: json_response(
            {
                "object": "list",
                "model": "emb",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.3]},
                    {"object": "embedding", "index": 0, "embedding": [0.1]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            }
        )
    )
    resp = await _provider(http, settings).embed(model_cfg("openai", "emb"), ["a", "b"], 256, {})
    assert rec.last_json == {
        "model": "emb",
        "input": ["a", "b"],
        "encoding_format": "float",
        "dimensions": 256,
    }
    assert resp.vectors == [[0.1], [0.3]]
    assert resp.usage.prompt_tokens == 4


def _status(status: int, body: dict | None = None, headers: dict | None = None):
    return lambda r: httpx2.Response(
        status, json=body or {"error": {"message": f"err {status}"}}, headers=headers
    )


@pytest.mark.parametrize(
    ("handler", "expected", "retryable"),
    [
        (_status(429, headers={"retry-after": "3"}), e.UpstreamRateLimited, True),
        (_status(500), e.UpstreamError, True),
        (_status(503), e.UpstreamError, True),
        (_status(400, {"error": {"message": "bad param x"}}), e.UpstreamBadRequest, False),
        (_status(422), e.UpstreamBadRequest, False),
        (_status(401), e.UpstreamError, True),
        (_status(403), e.UpstreamError, True),
        (_status(404), e.UpstreamError, True),
    ],
)
async def test_error_mapping(mock_http, settings, handler, expected, retryable):
    http, _ = mock_http(handler)
    with pytest.raises(e.GatewayError) as info:
        await _provider(http, settings).chat(MODEL, _req())
    assert type(info.value) is expected
    assert info.value.retryable is retryable


async def test_bad_request_forwards_upstream_message(mock_http, settings):
    http, _ = mock_http(_status(400, {"error": {"message": "bad param x"}}))
    with pytest.raises(e.UpstreamBadRequest, match="bad param x"):
        await _provider(http, settings).chat(MODEL, _req())


async def test_rate_limit_keeps_retry_after(mock_http, settings):
    http, _ = mock_http(_status(429, headers={"retry-after": "3"}))
    with pytest.raises(e.UpstreamRateLimited) as info:
        await _provider(http, settings).chat(MODEL, _req())
    assert info.value.headers == {"Retry-After": "3"}


async def test_timeout_and_connection_errors(mock_http, settings):
    def timeout(r):
        raise httpx2.ReadTimeout("slow", request=r)

    def conn(r):
        raise httpx2.ConnectError("refused", request=r)

    http, _ = mock_http(timeout)
    with pytest.raises(e.UpstreamTimeout):
        await _provider(http, settings).chat(MODEL, _req())
    http, _ = mock_http(conn)
    with pytest.raises(e.UpstreamError) as info:
        await _provider(http, settings).chat(MODEL, _req())
    assert type(info.value) is e.UpstreamError and info.value.retryable


async def test_stream_error_before_first_chunk(mock_http, settings):
    http, _ = mock_http(_status(503))
    with pytest.raises(e.UpstreamError):
        async for _ in _provider(http, settings).chat_stream(MODEL, _req()):
            pass


async def test_health(mock_http, settings):
    http, _ = mock_http(lambda r: json_response({"object": "list", "data": []}))
    assert (await _provider(http, settings).health()).ok
    http, _ = mock_http(_status(401))
    health = await _provider(http, settings).health()
    assert not health.ok and "autentikasi" in health.detail
