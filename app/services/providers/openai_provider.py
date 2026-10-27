"""Adapter OpenAI. Format API gateway = format OpenAI, jadi adapter ini paling tipis dan menjadi
kelas dasar LocalRuntimeProvider. Pembuatan payload, parsing respons/chunk, dan mapping error
sengaja dipisah ke method agar bisa di-override."""

import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx2
import openai

from app.schemas.catalog import ModelConfig
from app.schemas.unified import (
    FunctionCall,
    ProviderHealth,
    ToolCall,
    ToolCallDelta,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedCompletionRequest,
    UnifiedCompletionResponse,
    UnifiedEmbeddingResponse,
    Usage,
)
from app.services.providers.base import BaseProvider, drop_none
from app.utils.errors import (
    GatewayError,
    UpstreamBadRequest,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamTimeout,
)

# Opsi yang dibaca gateway sendiri, tidak diteruskan ke upstream.
GATEWAY_ONLY_OPTIONS = frozenset({"include_reasoning"})


def parse_usage(data: dict[str, Any] | None) -> Usage | None:
    if not data:
        return None
    details = data.get("prompt_tokens_details") or {}
    return Usage(
        prompt_tokens=data.get("prompt_tokens") or 0,
        completion_tokens=data.get("completion_tokens") or 0,
        cached_tokens=details.get("cached_tokens") or 0,
    )


class OpenAIProvider(BaseProvider):
    code: ClassVar[str] = "openai"
    default_base_url: ClassVar[str | None] = None  # None = default SDK

    _client_cache: openai.AsyncOpenAI | None = None

    # ------------------------------------------------------------------ klien
    def client_timeout(self) -> httpx2.Timeout:
        return httpx2.Timeout(float(self.cfg.timeout_seconds), connect=10.0)

    def default_headers(self) -> dict[str, str]:
        return {}

    def request_headers(self) -> dict[str, str]:
        """Header per request (mis. X-Request-ID untuk runtime lokal)."""
        return {}

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client_cache is None:
            self._client_cache = openai.AsyncOpenAI(
                api_key=self.api_key or "missing",
                base_url=self.cfg.base_url or self.default_base_url,
                http_client=self.http,
                max_retries=0,  # retry/fallback ditangani gateway
                timeout=self.client_timeout(),
                default_headers=self.default_headers() or None,
            )
        return self._client_cache

    # --------------------------------------------------------------- payload
    def build_chat_payload(self, model: ModelConfig, req: UnifiedChatRequest) -> dict[str, Any]:
        max_tokens_param = model.config.get("max_tokens_param", "max_tokens")
        payload = drop_none(
            {
                "model": model.upstream_name,
                "messages": [m.model_dump(exclude_none=True) for m in req.messages],
                "tools": [t.model_dump(exclude_none=True) for t in req.tools]
                if req.tools
                else None,
                "tool_choice": req.tool_choice,
                "response_format": req.response_format,
                "temperature": req.temperature,
                "top_p": req.top_p,
                max_tokens_param: req.max_tokens,
                "stop": req.stop,
                "seed": req.seed,
                "user": req.user,
            }
        )
        payload.update(self._passthrough(req.provider_options))
        return payload

    def build_completion_payload(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> dict[str, Any]:
        payload = drop_none(
            {
                "model": model.upstream_name,
                "prompt": req.prompt,
                "suffix": req.suffix,
                "max_tokens": req.max_tokens,
                "temperature": req.temperature,
                "top_p": req.top_p,
                "stop": req.stop,
                "seed": req.seed,
            }
        )
        payload.update(self._passthrough(req.provider_options))
        return payload

    @staticmethod
    def _passthrough(options: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in options.items() if k not in GATEWAY_ONLY_OPTIONS}

    @staticmethod
    def _split(payload: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
        """Field wajib sebagai kwarg SDK, sisanya via extra_body (meneruskan field apa adanya
        termasuk yang belum dikenal SDK)."""
        kwargs = {k: payload[k] for k in required}
        extra = {k: v for k, v in payload.items() if k not in required}
        if extra:
            kwargs["extra_body"] = extra
        return kwargs

    # -------------------------------------------------------------- respons
    def map_chat_response(self, data: dict[str, Any], model: ModelConfig) -> UnifiedChatResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = [
            ToolCall(
                id=tc.get("id") or "",
                function=FunctionCall(
                    name=(tc.get("function") or {}).get("name") or "",
                    arguments=(tc.get("function") or {}).get("arguments") or "",
                ),
            )
            for tc in message.get("tool_calls") or []
        ]
        return UnifiedChatResponse(
            content=message.get("content"),
            tool_calls=tool_calls or None,
            finish_reason=choice.get("finish_reason"),
            usage=parse_usage(data.get("usage")) or Usage(),
            upstream_model=data.get("model") or model.upstream_name,
            raw_id=data.get("id"),
            reasoning_content=message.get("reasoning_content"),
        )

    def map_chat_chunk(self, data: dict[str, Any]) -> UnifiedChunk | None:
        choices = data.get("choices") or []
        usage = parse_usage(data.get("usage"))
        if not choices:
            if usage is None:
                return None
            return UnifiedChunk(usage=usage, upstream_model=data.get("model"))
        choice = choices[0]
        delta = choice.get("delta") or {}
        deltas = [
            ToolCallDelta(
                index=tc.get("index", i),
                id=tc.get("id"),
                name=(tc.get("function") or {}).get("name"),
                arguments=(tc.get("function") or {}).get("arguments"),
            )
            for i, tc in enumerate(delta.get("tool_calls") or [])
        ]
        chunk = UnifiedChunk(
            delta_content=delta.get("content"),
            delta_reasoning=delta.get("reasoning_content"),
            delta_tool_calls=deltas or None,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            upstream_model=data.get("model"),
            raw_id=data.get("id"),
        )
        empty = (
            chunk.delta_content is None
            and chunk.delta_reasoning is None
            and not deltas
            and chunk.finish_reason is None
            and usage is None
        )
        return None if empty else chunk

    def map_completion_response(
        self, data: dict[str, Any], model: ModelConfig
    ) -> UnifiedCompletionResponse:
        choice = (data.get("choices") or [{}])[0]
        return UnifiedCompletionResponse(
            text=choice.get("text") or "",
            finish_reason=choice.get("finish_reason"),
            usage=parse_usage(data.get("usage")) or Usage(),
            upstream_model=data.get("model") or model.upstream_name,
            raw_id=data.get("id"),
        )

    def map_completion_chunk(self, data: dict[str, Any]) -> UnifiedChunk | None:
        choices = data.get("choices") or []
        usage = parse_usage(data.get("usage"))
        if not choices:
            return UnifiedChunk(usage=usage) if usage else None
        choice = choices[0]
        text = choice.get("text")
        if not text and choice.get("finish_reason") is None and usage is None:
            return None
        return UnifiedChunk(
            delta_content=text or None,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            upstream_model=data.get("model"),
            raw_id=data.get("id"),
        )

    # ----------------------------------------------------------------- error
    def map_error(self, exc: Exception) -> GatewayError:
        if isinstance(exc, GatewayError):
            return exc
        name = self.cfg.code
        if isinstance(exc, openai.APITimeoutError):
            return UpstreamTimeout(f"{name}: timeout")
        if isinstance(exc, openai.APIConnectionError):
            return UpstreamError(f"{name}: koneksi gagal ({exc})")
        if isinstance(exc, openai.RateLimitError):
            retry_after = exc.response.headers.get("retry-after") if exc.response else None
            return UpstreamRateLimited(
                f"{name}: rate limited",
                headers={"Retry-After": retry_after} if retry_after else None,
            )
        if isinstance(exc, openai.BadRequestError | openai.UnprocessableEntityError):
            return UpstreamBadRequest(f"{name}: {_upstream_message(exc)}")
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            self.log.error("provider key invalid", provider=name, status=exc.status_code)
            return UpstreamError(f"{name}: autentikasi provider gagal")
        if isinstance(exc, openai.NotFoundError):
            self.log.error("upstream model not found", provider=name, error=_upstream_message(exc))
            return UpstreamError(f"{name}: model upstream tidak ditemukan")
        if isinstance(exc, openai.APIStatusError):
            if exc.status_code >= 500:
                return UpstreamError(f"{name}: upstream {exc.status_code}")
            return UpstreamBadRequest(f"{name}: {_upstream_message(exc)}")
        if isinstance(exc, httpx2.TimeoutException):
            return UpstreamTimeout(f"{name}: timeout")
        if isinstance(exc, httpx2.HTTPError):
            return UpstreamError(f"{name}: {type(exc).__name__}")
        return UpstreamError(f"{name}: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ chat
    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse:
        payload = self.build_chat_payload(model, req)
        async with self.semaphore:
            try:
                resp = await self.client.chat.completions.create(
                    **self._split(payload, ("model", "messages")),
                    extra_headers=self.request_headers() or None,
                )
            except Exception as exc:
                raise self.map_error(exc) from exc
        return self.map_chat_response(resp.model_dump(), model)

    async def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]:
        payload = self.build_chat_payload(model, req)
        payload["stream_options"] = {"include_usage": True}
        async with self.semaphore:
            try:
                stream = await self.client.chat.completions.create(
                    **self._split(payload, ("model", "messages")),
                    stream=True,
                    extra_headers=self.request_headers() or None,
                )
                async with stream:
                    async for chunk in self.first_chunk_guard(stream):
                        mapped = self.map_chat_chunk(chunk.model_dump())
                        if mapped is not None:
                            yield mapped
            except Exception as exc:
                raise self.map_error(exc) from exc

    def first_chunk_guard(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """Hook untuk timeout chunk pertama (dipakai provider lokal)."""
        return stream

    # ------------------------------------------------------------ completion
    async def completion(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> UnifiedCompletionResponse:
        payload = self.build_completion_payload(model, req)
        async with self.semaphore:
            try:
                resp = await self.client.completions.create(
                    **self._split(payload, ("model", "prompt")),
                    extra_headers=self.request_headers() or None,
                )
            except Exception as exc:
                raise self.map_error(exc) from exc
        return self.map_completion_response(resp.model_dump(), model)

    async def completion_stream(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> AsyncIterator[UnifiedChunk]:
        payload = self.build_completion_payload(model, req)
        payload["stream_options"] = {"include_usage": True}
        async with self.semaphore:
            try:
                stream = await self.client.completions.create(
                    **self._split(payload, ("model", "prompt")),
                    stream=True,
                    extra_headers=self.request_headers() or None,
                )
                async with stream:
                    async for chunk in self.first_chunk_guard(stream):
                        mapped = self.map_completion_chunk(chunk.model_dump())
                        if mapped is not None:
                            yield mapped
            except Exception as exc:
                raise self.map_error(exc) from exc

    # ------------------------------------------------------------- embedding
    async def embed(
        self,
        model: ModelConfig,
        inputs: list[str],
        dimensions: int | None,
        provider_options: dict[str, Any],
    ) -> UnifiedEmbeddingResponse:
        extra = drop_none({"dimensions": dimensions, **self._passthrough(provider_options)})
        async with self.semaphore:
            try:
                resp = await self.client.embeddings.create(
                    model=model.upstream_name,
                    input=inputs,
                    encoding_format="float",
                    extra_body=extra or None,
                    extra_headers=self.request_headers() or None,
                )
            except Exception as exc:
                raise self.map_error(exc) from exc
        return self.map_embedding_response(resp.model_dump(), model)

    def map_embedding_response(
        self, data: dict[str, Any], model: ModelConfig
    ) -> UnifiedEmbeddingResponse:
        items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
        usage = data.get("usage") or {}
        return UnifiedEmbeddingResponse(
            vectors=[d["embedding"] for d in items],
            usage=Usage(prompt_tokens=usage.get("prompt_tokens") or 0),
            upstream_model=data.get("model") or model.upstream_name,
        )

    # ---------------------------------------------------------------- health
    async def health(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            await self.client.models.list(timeout=self.settings.provider_health_timeout_s)
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(ok=False, detail=self.map_error(exc).message)
        return ProviderHealth(ok=True, latency_ms=int((time.perf_counter() - start) * 1000))

    async def shutdown(self) -> None:
        # http_client dimiliki registry; jangan ditutup di sini.
        self._client_cache = None


def _upstream_message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return getattr(exc, "message", None) or str(exc)
