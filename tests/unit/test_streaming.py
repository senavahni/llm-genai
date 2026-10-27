import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest

from app.core.config import get_settings
from app.schemas.catalog import ModelConfig, ProviderConfig
from app.schemas.unified import UnifiedChatRequest, UnifiedMessage
from app.utils.errors import UpstreamError
from app.utils.streaming import (
    SSE_DONE,
    SSE_PING,
    StreamOutcome,
    drain_finishers,
    guarded_stream,
    parse_sse_lines,
    sse_event,
)
from tests.fakes.fake_provider import FakeProvider

MODEL = ModelConfig(
    id=uuid.uuid4(), alias="fake/m", provider_code="fake", upstream_name="m", model_type="chat"
)
REQ = UnifiedChatRequest(messages=[UnifiedMessage(role="user", content="hi")])


def _provider(**kw) -> FakeProvider:
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="fake",
        kind="remote",
        display_name="Fake",
        base_url=None,
        api_key_env=None,
    )
    return FakeProvider(cfg, None, get_settings(), **kw)  # type: ignore[arg-type]


async def _sse_source(provider: FakeProvider, outcome: StreamOutcome) -> AsyncIterator[bytes]:
    async for chunk in provider.chat_stream(MODEL, REQ):
        if chunk.usage:
            outcome.usage = chunk.usage
        yield sse_event(chunk.model_dump(exclude_none=True))
    yield SSE_DONE


class _Req:
    def __init__(self, disconnected: bool = False) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[StreamOutcome] = []

    async def __call__(self, outcome: StreamOutcome) -> None:
        self.calls.append(outcome)


async def test_success_calls_on_finish_once():
    rec, outcome = _Recorder(), StreamOutcome()
    provider = _provider()
    out = [
        b
        async for b in guarded_stream(_sse_source(provider, outcome), _Req(), rec, outcome=outcome)
    ]
    await drain_finishers()
    assert out[-1] == SSE_DONE
    assert len(rec.calls) == 1
    assert rec.calls[0].status == "success"
    assert rec.calls[0].usage.completion_tokens == 3
    assert rec.calls[0].ttft_ms is not None
    assert rec.calls[0].chunks == len(out)


async def test_error_mid_stream_calls_on_finish_once():
    rec, outcome = _Recorder(), StreamOutcome()
    received = []
    with pytest.raises(UpstreamError):
        async for b in guarded_stream(
            _sse_source(_provider(mode="fail_mid"), outcome), _Req(), rec, outcome=outcome
        ):
            received.append(b)
    await drain_finishers()
    assert len(received) == 1
    assert len(rec.calls) == 1
    assert rec.calls[0].status == "error"
    assert isinstance(rec.calls[0].error, UpstreamError)


async def test_client_disconnect_aclose_calls_on_finish_once_and_closes_upstream():
    rec, outcome = _Recorder(), StreamOutcome()
    provider = _provider(chunks=["a", "b", "c", "d"])
    gen = guarded_stream(_sse_source(provider, outcome), _Req(), rec, outcome=outcome)
    assert await gen.__anext__()
    await gen.aclose()  # Starlette menutup generator saat client putus
    await drain_finishers()
    assert len(rec.calls) == 1
    assert rec.calls[0].status == "cancelled"
    assert provider.closed  # upstream ikut ditutup


async def test_task_cancellation_calls_on_finish_once():
    rec, outcome = _Recorder(), StreamOutcome()
    provider = _provider(mode="slow", delay_s=0.2, chunks=["a", "b", "c"])

    async def consume():
        async for _ in guarded_stream(
            _sse_source(provider, outcome), _Req(), rec, outcome=outcome, heartbeat_s=0
        ):
            pass

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drain_finishers()
    assert len(rec.calls) == 1
    assert rec.calls[0].status == "cancelled"


async def test_heartbeat_and_disconnect_detection():
    rec = _Recorder()
    req = _Req()

    async def slow() -> AsyncIterator[bytes]:
        yield b"data: 1\n\n"
        await asyncio.sleep(10)
        yield b"data: never\n\n"

    gen = guarded_stream(slow(), req, rec, heartbeat_s=0.05)
    assert await gen.__anext__() == b"data: 1\n\n"
    assert await gen.__anext__() == SSE_PING
    req.disconnected = True
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    await drain_finishers()
    assert [c.status for c in rec.calls] == ["cancelled"]


async def test_on_finish_failure_is_contained():
    async def boom(_: StreamOutcome) -> None:
        raise RuntimeError("db down")

    async def src() -> AsyncIterator[bytes]:
        yield b"x"

    assert [b async for b in guarded_stream(src(), None, boom)] == [b"x"]
    await drain_finishers()


def test_sse_event_format():
    assert sse_event({"a": 1}) == b'data: {"a":1}\n\n'
    assert sse_event("[DONE]") == SSE_DONE


async def _lines(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def test_parse_sse_multiline_keepalive_and_events():
    events = [
        e
        async for e in parse_sse_lines(
            _lines(
                ": keep-alive",
                "",
                "event: message_start",
                'data: {"a":',
                "data: 1}",
                "",
                ": ping",
                "data:no-space",
                "id: 7",
                "retry: 1000",
                "",
                "",
                "data: [DONE]",
            )
        )
    ]
    assert [(e.event, e.data) for e in events] == [
        ("message_start", '{"a":\n1}'),
        ("message", "no-space"),
        ("message", "[DONE]"),
    ]
    assert events[1].id == "7"


async def test_parse_sse_crlf():
    events = [e async for e in parse_sse_lines(_lines("data: x\r\n", "\r\n"))]
    assert [e.data for e in events] == ["x"]
