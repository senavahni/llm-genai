"""Pure ASGI middleware (bukan BaseHTTPMiddleware) agar streaming tidak di-buffer."""

import time
import uuid
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.helper import client_ip, new_request_id
from app.utils.logger import ACCESS_LOGGER, get_logger

REQUEST_ID_HEADER = b"x-request-id"

access_log = get_logger(ACCESS_LOGGER)


def _incoming_request_id(scope: Scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == REQUEST_ID_HEADER:
            try:
                return str(uuid.UUID(value.decode("latin-1").strip()))
            except ValueError:
                return None
    return None


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, trust_proxy: bool = False) -> None:
        self.app = app
        self.trust_proxy = trust_proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        request_id = _incoming_request_id(scope) or str(new_request_id())
        ip = client_ip(scope, self.trust_proxy)
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, client_ip=ip, path=scope.get("path")
        )

        status = 500
        bytes_sent = 0
        rid_bytes = request_id.encode("latin-1")

        async def send_wrapper(message: Message) -> None:
            nonlocal status, bytes_sent
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers") or [])
                if not any(k.lower() == REQUEST_ID_HEADER for k, _ in headers):
                    headers.append((REQUEST_ID_HEADER, rid_bytes))
                message["headers"] = headers
            elif message["type"] == "http.response.body":
                bytes_sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            auth = state.get("auth")
            ctx = structlog.contextvars.get_contextvars()
            access_log.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                request_id=request_id,
                project_slug=getattr(auth, "project_slug", None) or ctx.get("project_slug"),
                key_prefix=getattr(auth, "key_prefix", None) or ctx.get("key_prefix"),
                bytes_sent=bytes_sent,
                user_agent=_header(scope, b"user-agent"),
            )
            structlog.contextvars.clear_contextvars()
