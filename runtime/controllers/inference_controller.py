import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.utils.errors import InvalidRequestError
from app.utils.streaming import SSE_DONE, SSE_HEADERS, sse_event
from runtime.core.state import RuntimeState


def _state(request: Request) -> RuntimeState:
    return request.app.state.rt  # type: ignore[no-any-return]


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise InvalidRequestError("Body harus JSON") from exc
    if not isinstance(body, dict) or not body.get("model"):
        raise InvalidRequestError("Field 'model' wajib diisi", param="model")
    return body


@contextlib.asynccontextmanager
async def _watch_disconnect(request: Request, cancel: asyncio.Event) -> AsyncIterator[None]:
    """Gateway putus saat inferensi non-stream (mis. gambar) → set cancel."""

    async def watch() -> None:
        while not cancel.is_set():
            if await request.is_disconnected():
                cancel.set()
                return
            await asyncio.sleep(0.5)

    task = asyncio.ensure_future(watch())
    try:
        yield
    finally:
        task.cancel()


async def _sse(
    source: AsyncIterator[dict[str, Any]], cancel: asyncio.Event
) -> AsyncIterator[bytes]:
    try:
        async for chunk in source:
            yield sse_event(chunk)
        yield SSE_DONE
    finally:
        cancel.set()  # disconnect (CancelledError/GeneratorExit) → hentikan generasi di thread
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()


async def _generate(request: Request, method: str) -> JSONResponse | StreamingResponse:
    body = await _body(request)
    service = _state(request).service
    request_id = _request_id(request)
    if body.get("stream"):
        cancel = asyncio.Event()
        source = await service.open_stream(method, body, request_id, cancel)
        return StreamingResponse(
            _sse(source, cancel), media_type="text/event-stream", headers=SSE_HEADERS
        )
    result = await getattr(service, method)(body, request_id)
    return JSONResponse(result)


async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    return await _generate(request, "chat")


async def completions(request: Request) -> JSONResponse | StreamingResponse:
    return await _generate(request, "completion")


async def embeddings(request: Request) -> JSONResponse:
    body = await _body(request)
    return JSONResponse(await _state(request).service.embeddings(body, _request_id(request)))


async def image_generations(request: Request) -> JSONResponse:
    body = await _body(request)
    cancel = asyncio.Event()
    async with _watch_disconnect(request, cancel):
        result = await _state(request).service.images(body, _request_id(request), cancel)
    return JSONResponse(result)
