from collections.abc import AsyncIterator
from typing import Any, ClassVar

import anthropic
import httpx2

from app.schemas.catalog import ModelConfig
from app.schemas.unified import (
    ProviderHealth,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
)
from app.services.providers.base import BaseProvider
from app.services.providers.translate import anthropic_map
from app.utils.errors import (
    GatewayError,
    UpstreamBadRequest,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamTimeout,
)


class AnthropicProvider(BaseProvider):
    """Claude via Messages API. Embeddings tidak didukung (default BaseProvider)."""

    code: ClassVar[str] = "anthropic"
    _client_cache: anthropic.AsyncAnthropic | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client_cache is None:
            self._client_cache = anthropic.AsyncAnthropic(
                api_key=self.api_key or "missing",
                base_url=self.cfg.base_url or None,
                http_client=self.http,
                max_retries=0,
                timeout=httpx2.Timeout(float(self.cfg.timeout_seconds), connect=10.0),
            )
        return self._client_cache

    @staticmethod
    def _kwargs(payload: dict[str, Any]) -> dict[str, Any]:
        required = ("model", "messages", "max_tokens")
        kwargs = {k: payload[k] for k in required}
        extra = {k: v for k, v in payload.items() if k not in required}
        if extra:
            kwargs["extra_body"] = extra
        return kwargs

    def map_error(self, exc: Exception) -> GatewayError:
        if isinstance(exc, GatewayError):
            return exc
        if isinstance(exc, anthropic.APITimeoutError):
            return UpstreamTimeout("anthropic: timeout")
        if isinstance(exc, anthropic.APIConnectionError):
            return UpstreamError(f"anthropic: koneksi gagal ({exc})")
        if isinstance(exc, anthropic.RateLimitError):
            retry_after = exc.response.headers.get("retry-after") if exc.response else None
            return UpstreamRateLimited(
                "anthropic: rate limited",
                headers={"Retry-After": retry_after} if retry_after else None,
            )
        if isinstance(exc, anthropic.BadRequestError):
            return UpstreamBadRequest(f"anthropic: {_message(exc)}")
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            self.log.error("provider key invalid", provider="anthropic", status=exc.status_code)
            return UpstreamError("anthropic: autentikasi provider gagal")
        if isinstance(exc, anthropic.NotFoundError):
            self.log.error("upstream model not found", provider="anthropic", error=_message(exc))
            return UpstreamError("anthropic: model upstream tidak ditemukan")
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code >= 500:  # termasuk 529 overloaded
                return UpstreamError(f"anthropic: upstream {exc.status_code} ({_message(exc)})")
            return UpstreamBadRequest(f"anthropic: {_message(exc)}")
        if isinstance(exc, httpx2.TimeoutException):
            return UpstreamTimeout("anthropic: timeout")
        return UpstreamError(f"anthropic: {type(exc).__name__}: {exc}")

    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse:
        built = anthropic_map.build_payload(model, req)
        async with self.semaphore:
            try:
                msg = await self.client.messages.create(**self._kwargs(built.payload))
            except Exception as exc:
                raise self.map_error(exc) from exc
        resp = anthropic_map.parse_response(
            msg.model_dump(),
            include_reasoning=bool(req.provider_options.get("include_reasoning")),
            prefill=built.prefill,
        )
        resp.upstream_model = resp.upstream_model or model.upstream_name
        return resp

    async def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]:
        built = anthropic_map.build_payload(model, req)
        translator = anthropic_map.StreamTranslator(
            include_reasoning=bool(req.provider_options.get("include_reasoning")),
            prefill=built.prefill,
        )
        async with self.semaphore:
            try:
                stream = await self.client.messages.create(
                    **self._kwargs(built.payload), stream=True
                )
                async with stream:
                    async for event in stream:
                        for chunk in translator.feed(event.model_dump()):
                            yield chunk
            except Exception as exc:
                raise self.map_error(exc) from exc

    async def health(self) -> ProviderHealth:
        try:
            await self.client.models.list(limit=1, timeout=self.settings.provider_health_timeout_s)
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(ok=False, detail=self.map_error(exc).message)
        return ProviderHealth(ok=True)

    async def shutdown(self) -> None:
        self._client_cache = None


def _message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return getattr(exc, "message", None) or str(exc)
