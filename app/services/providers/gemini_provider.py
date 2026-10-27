from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx
import httpx2
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas.catalog import ModelConfig
from app.schemas.unified import (
    ProviderHealth,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedEmbeddingResponse,
    Usage,
)
from app.services.providers.base import BaseProvider
from app.services.providers.translate import gemini_map
from app.utils.errors import (
    GatewayError,
    UpstreamBadRequest,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamTimeout,
)
from app.utils.helper import estimate_tokens


class GeminiProvider(BaseProvider):
    code: ClassVar[str] = "gemini"
    _client_cache: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client_cache is None:
            options: dict[str, Any] = {
                "timeout": int(self.cfg.timeout_seconds * 1000),
                "httpx_async_client": self.http,
            }
            if self.cfg.base_url:
                options["base_url"] = self.cfg.base_url
            self._client_cache = genai.Client(
                api_key=self.api_key or "missing", http_options=types.HttpOptions(**options)
            )
        return self._client_cache

    def map_error(self, exc: Exception) -> GatewayError:
        if isinstance(exc, GatewayError):
            return exc
        if isinstance(exc, genai_errors.APIError):
            code = exc.code or 0
            message = f"gemini: {code} {exc.message or exc.status or ''}".strip()
            if code == 429:
                return UpstreamRateLimited(message)
            if code >= 500:
                return UpstreamError(message)
            if code in (401, 403):
                self.log.error("provider key invalid", provider="gemini", status=code)
                return UpstreamError("gemini: autentikasi provider gagal")
            if code == 404:
                self.log.error("upstream model not found", provider="gemini", error=message)
                return UpstreamError("gemini: model upstream tidak ditemukan")
            return UpstreamBadRequest(message)
        if isinstance(exc, httpx.TimeoutException | httpx2.TimeoutException | TimeoutError):
            return UpstreamTimeout("gemini: timeout")
        if isinstance(exc, httpx.HTTPError | httpx2.HTTPError):
            return UpstreamError(f"gemini: {type(exc).__name__}")
        return UpstreamError(f"gemini: {type(exc).__name__}: {exc}")

    @staticmethod
    def _dump(resp: Any) -> dict[str, Any]:
        return resp.model_dump(mode="json", exclude_none=True)  # type: ignore[no-any-return]

    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse:
        contents, config = gemini_map.build_request(model, req)
        async with self.semaphore:
            try:
                resp = await self.client.aio.models.generate_content(
                    model=model.upstream_name,
                    contents=contents,  # type: ignore[arg-type]
                    config=config,  # type: ignore[arg-type]
                )
            except Exception as exc:
                raise self.map_error(exc) from exc
        return gemini_map.parse_response(
            self._dump(resp),
            include_reasoning=bool(req.provider_options.get("include_reasoning")),
            upstream_model=model.upstream_name,
        )

    async def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]:
        contents, config = gemini_map.build_request(model, req)
        translator = gemini_map.StreamTranslator(
            include_reasoning=bool(req.provider_options.get("include_reasoning"))
        )
        async with self.semaphore:
            try:
                stream = await self.client.aio.models.generate_content_stream(
                    model=model.upstream_name,
                    contents=contents,  # type: ignore[arg-type]
                    config=config,  # type: ignore[arg-type]
                )
                async for resp in stream:
                    for chunk in translator.feed(self._dump(resp)):
                        yield chunk
            except Exception as exc:
                raise self.map_error(exc) from exc
        final = translator.finish()
        final.upstream_model = final.upstream_model or model.upstream_name
        yield final

    async def embed(
        self,
        model: ModelConfig,
        inputs: list[str],
        dimensions: int | None,
        provider_options: dict[str, Any],
    ) -> UnifiedEmbeddingResponse:
        config: dict[str, Any] = dict(provider_options)
        if dimensions is not None:
            config["output_dimensionality"] = dimensions
        async with self.semaphore:
            try:
                resp = await self.client.aio.models.embed_content(
                    model=model.upstream_name,
                    contents=inputs,  # type: ignore[arg-type]
                    config=config or None,  # type: ignore[arg-type]
                )
            except Exception as exc:
                raise self.map_error(exc) from exc
        vectors = [list(e.values or []) for e in resp.embeddings or []]
        # Gemini tidak mengembalikan token usage untuk embedding → estimasi.
        return UnifiedEmbeddingResponse(
            vectors=vectors,
            usage=Usage(prompt_tokens=estimate_tokens(inputs), estimated=True),
            upstream_model=model.upstream_name,
        )

    async def health(self) -> ProviderHealth:
        try:
            pager = await self.client.aio.models.list(config={"page_size": 1})
            _ = pager.page
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(ok=False, detail=self.map_error(exc).message)
        return ProviderHealth(ok=True)

    async def shutdown(self) -> None:
        self._client_cache = None
