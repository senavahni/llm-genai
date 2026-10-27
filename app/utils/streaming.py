"""Utilitas SSE: format event keluar, guard stream (disconnect/cancel/heartbeat), parser SSE
upstream."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import orjson

from app.schemas.unified import Usage
from app.utils.logger import get_logger

log = get_logger(__name__)

SSE_DONE = b"data: [DONE]\n\n"
SSE_PING = b": ping\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

StreamStatus = Literal["success", "error", "cancelled"]


def sse_event(data: dict[str, Any] | str) -> bytes:
    payload = data.encode() if isinstance(data, str) else orjson.dumps(data)
    return b"data: " + payload + b"\n\n"


@dataclass
class StreamOutcome:
    """Diisi bersama: source generator boleh mengisi `usage`/`extra`; guarded_stream mengisi
    status, ttft_ms, latency_ms, error."""

    status: StreamStatus = "success"
    usage: Usage | None = None
    ttft_ms: int | None = None
    latency_ms: int | None = None
    error: BaseException | None = None
    chunks: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class _DisconnectAware(Protocol):
    async def is_disconnected(self) -> bool: ...


_finishers: set[asyncio.Task[None]] = set()


async def drain_finishers() -> None:
    """Tunggu semua callback on_finish selesai (shutdown & test)."""
    while _finishers:
        await asyncio.gather(*list(_finishers), return_exceptions=True)


async def _run_on_finish(
    on_finish: Callable[[StreamOutcome], Awaitable[None]], outcome: StreamOutcome
) -> None:
    try:
        await on_finish(outcome)
    except Exception as exc:  # noqa: BLE001 - pencatatan tidak boleh menjatuhkan proses
        log.error("stream_on_finish_failed", error=str(exc), exc_info=exc)


async def guarded_stream(
    source: AsyncIterator[bytes],
    request: _DisconnectAware | None,
    on_finish: Callable[[StreamOutcome], Awaitable[None]],
    *,
    outcome: StreamOutcome | None = None,
    heartbeat_s: float = 15.0,
) -> AsyncIterator[bytes]:
    """Yield bytes dari `source`; deteksi disconnect; tangkap CancelledError/GeneratorExit;
    panggil on_finish(outcome) TEPAT SEKALI di finally (task terpisah + shield, sehingga
    pencatatan tetap selesai walau client putus). Heartbeat `: ping` bila diam > heartbeat_s."""
    outcome = outcome or StreamOutcome()
    start = time.perf_counter()
    iterator = source.__aiter__()
    pending: asyncio.Task[bytes] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            if heartbeat_s > 0:
                done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
                if not done:
                    if request is not None and await request.is_disconnected():
                        outcome.status = "cancelled"
                        return
                    yield SSE_PING
                    continue
            try:
                chunk = await pending
            except StopAsyncIteration:
                pending = None
                break
            pending = None
            if outcome.ttft_ms is None:
                outcome.ttft_ms = int((time.perf_counter() - start) * 1000)
            outcome.chunks += 1
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        outcome.status = "cancelled"
        raise
    except Exception as exc:
        outcome.status = "error"
        outcome.error = exc
        raise
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(BaseException):
                await pending
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(BaseException):
                await aclose()
        outcome.latency_ms = int((time.perf_counter() - start) * 1000)
        task = asyncio.ensure_future(_run_on_finish(on_finish, outcome))
        _finishers.add(task)
        task.add_done_callback(_finishers.discard)
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(task)


# --------------------------------------------------------------- parser SSE upstream
@dataclass(frozen=True, slots=True)
class SSEEvent:
    event: str
    data: str
    id: str | None = None


async def parse_sse_lines(lines: AsyncIterator[str]) -> AsyncIterator[SSEEvent]:
    """Parser SSE sesuai spesifikasi WHATWG: `data:` multi-baris digabung dengan newline,
    komentar (`:`) seperti keep-alive diabaikan, event dikirim saat baris kosong."""
    event = ""
    data: list[str] = []
    last_id: str | None = None
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield SSEEvent(event or "message", "\n".join(data), last_id)
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            data.append(value)
        elif name == "event":
            event = value
        elif name == "id":
            last_id = value
        # `retry` dan field tak dikenal diabaikan
    if data:
        yield SSEEvent(event or "message", "\n".join(data), last_id)


async def aiter_sse(response: Any) -> AsyncIterator[SSEEvent]:
    """Iterasi event SSE dari respons httpx/httpx2 (`aiter_lines`)."""
    async for ev in parse_sse_lines(response.aiter_lines()):
        yield ev
