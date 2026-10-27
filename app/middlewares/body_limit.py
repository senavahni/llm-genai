from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middlewares.error_handler import gateway_error_response
from app.utils.errors import PayloadTooLarge


class BodySizeLimitMiddleware:
    """Tolak body > max_bytes dengan 413. Cek Content-Length di depan, lalu hitung byte aktual
    (untuk chunked upload) — exception dilempar dari receive() sehingga ditangani error handler."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _error(self) -> PayloadTooLarge:
        mb = self.max_bytes / (1024 * 1024)
        return PayloadTooLarge(f"Request body melebihi batas {mb:g} MB")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for key, value in scope.get("headers") or []:
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._reject(scope, send)
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise self._error()
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = (scope.get("state") or {}).get("request_id")
        response = gateway_error_response(self._error(), request_id)
        await response(scope, _drain_receive, send)


async def _drain_receive() -> Message:
    return {"type": "http.disconnect"}
