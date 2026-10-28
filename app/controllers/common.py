"""Helper bersama controller publik: router, pencatatan error, SSE setelah chunk pertama."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.schemas.converters import usage_chunk
from app.schemas.unified import UnifiedChunk
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router, aclose_quietly
from app.services.usage_service import usage_service
from app.utils.errors import GatewayError, ServiceUnavailable
from app.utils.logger import get_logger
from app.utils.streaming import SSE_DONE, SSE_HEADERS, StreamOutcome, guarded_stream, sse_event

log = get_logger(__name__)


def get_router(request: Request) -> Router:
    router = getattr(request.app.state, "router", None)
    if router is None:
        raise ServiceUnavailable("Gateway belum siap (registry tidak termuat)")
    return router  # type: ignore[no-any-return]


def payload_body(ctx_auth_log: bool, body: Any) -> dict[str, Any] | None:
    """Body request untuk log payload, hanya bila project mengizinkan."""
    if not ctx_auth_log:
        return None
    return body.model_dump(mode="json", exclude_none=True)  # type: ignore[no-any-return]


async def finish_error(ctx: RequestCtx, exc: BaseException, outcome: Outcome | None = None) -> None:
    """Catat request gagal/dibatalkan, lalu lampirkan header gateway ke error (attempts dll.)."""
    status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
    try:
        await usage_service.finish(ctx, outcome, status=status, error=exc)
    except Exception as log_exc:  # noqa: BLE001 - jangan menutupi error aslinya
        log.error("usage_finish_failed", error=str(log_exc))
    if isinstance(exc, GatewayError):
        for k, v in ctx.headers().items():
            exc.headers.setdefault(k, v)


def public_base(request: Request) -> str:
    if get_settings().trust_proxy:
        proto = request.headers.get("x-forwarded-proto")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if proto and host:
            return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"
    return str(request.base_url).rstrip("/")


def _has_payload(chunk: UnifiedChunk) -> bool:
    return bool(
        chunk.delta_content is not None
        or chunk.delta_reasoning is not None
        or chunk.delta_tool_calls
        or chunk.finish_reason
    )


async def open_sse(
    request: Request,
    ctx: RequestCtx,
    outcome: Outcome,
    gen: AsyncIterator[UnifiedChunk],
    encode: Callable[[UnifiedChunk, int], dict[str, Any]],
    *,
    include_usage: bool,
    model: str,
    chat: bool,
) -> StreamingResponse:
    """Tunggu chunk pertama dulu (fallback & error sebelum token pertama → status HTTP biasa,
    header X-Gateway-* berdasarkan kandidat yang memberi chunk pertama), baru buka SSE."""
    try:
        first: UnifiedChunk | None = await gen.__anext__()
    except StopAsyncIteration:
        first = None
    except BaseException as exc:
        await finish_error(ctx, exc, outcome)
        raise
    created = int(time.time())
    stream_outcome = StreamOutcome()
    role_pending = chat

    def event(chunk: UnifiedChunk) -> bytes:
        nonlocal role_pending
        data = encode(chunk, created)
        if role_pending:
            data["choices"][0]["delta"] = {"role": "assistant", **data["choices"][0]["delta"]}
            role_pending = False
        return sse_event(data)

    async def body() -> AsyncIterator[bytes]:
        try:
            if first is not None and _has_payload(first):
                yield event(first)
            async for chunk in gen:
                if _has_payload(chunk):
                    yield event(chunk)
            if include_usage:
                yield sse_event(
                    usage_chunk(outcome.usage, str(ctx.request_id), model, created, chat=chat)
                )
            yield SSE_DONE
        except GatewayError as exc:
            # setelah chunk pertama tidak ada fallback: error dikirim sebagai event SSE
            stream_outcome.status, stream_outcome.error = "error", exc
            yield sse_event(exc.to_openai_dict(str(ctx.request_id)))
            yield SSE_DONE
        finally:
            await aclose_quietly(gen)

    return StreamingResponse(
        guarded_stream(
            body(),
            request,
            usage_service.finish_stream(ctx, outcome),
            outcome=stream_outcome,
            heartbeat_s=get_settings().sse_heartbeat_s,
        ),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **ctx.headers()},
    )
