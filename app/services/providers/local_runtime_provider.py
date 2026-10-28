"""Adapter gateway → Local Runtime (OpenVINO di GPU/NPU). Runtime berbicara format OpenAI,
jadi kelas ini turunan OpenAIProvider (provider `openvino`)."""

import asyncio
import base64
import hashlib
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx2
import openai
import structlog

from app.schemas.catalog import ModelConfig
from app.schemas.unified import (
    ProviderHealth,
    RuntimeMeta,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedCompletionResponse,
    UnifiedEmbeddingResponse,
    UnifiedImage,
    UnifiedImageRequest,
    UnifiedImageResponse,
)
from app.services.providers.base import drop_none
from app.services.providers.openai_provider import OpenAIProvider
from app.utils.errors import (
    CapabilityNotSupported,
    ContextLengthExceeded,
    DeviceOOM,
    DeviceUnavailable,
    GatewayError,
    ModelBusy,
    ModelLoadFailed,
    RequestCancelled,
    UnsupportedParameter,
    UnsupportedSize,
    UpstreamBadRequest,
    UpstreamTimeout,
)

# code error runtime → error gateway. Semua error device bersifat retryable (UpstreamError)
# sehingga router fallback ke kandidat route berikutnya.
RUNTIME_ERROR_CODES: dict[str, type[GatewayError]] = {
    "model_busy": ModelBusy,
    "device_oom": DeviceOOM,
    "device_unavailable": DeviceUnavailable,
    "model_load_failed": ModelLoadFailed,
    "capability_not_supported": CapabilityNotSupported,
    "unsupported_size": UnsupportedSize,
    "unsupported_parameter": UnsupportedParameter,
    "context_length_exceeded": ContextLengthExceeded,
    "cancelled": RequestCancelled,
}


def parse_runtime_meta(data: dict[str, Any] | None) -> RuntimeMeta | None:
    meta = (data or {}).get("x_runtime")
    if not isinstance(meta, dict) or not meta.get("device"):
        return None
    return RuntimeMeta(
        device=meta["device"],
        backend=meta.get("backend") or "",
        load_ms=meta.get("load_ms") or 0,
        queue_ms=meta.get("queue_ms") or 0,
        infer_ms=meta.get("infer_ms"),
        warnings=list(meta.get("warnings") or []),
    )


class LocalRuntimeProvider(OpenAIProvider):
    code: ClassVar[str] = "local"

    # ------------------------------------------------------------------ klien
    @property
    def base_url(self) -> str:
        return (self.cfg.base_url or self.settings.runtime_url).rstrip("/")

    def client_timeout(self) -> httpx2.Timeout:
        # read timeout mencakup chunk pertama (swap model 7B bisa lama)
        read = float(max(self.cfg.timeout_seconds, self.settings.local_first_token_timeout_s))
        return httpx2.Timeout(read, connect=5.0)

    def default_headers(self) -> dict[str, str]:
        return {"X-Runtime-Token": self.settings.runtime_token.get_secret_value()}

    def request_headers(self) -> dict[str, str]:
        request_id = structlog.contextvars.get_contextvars().get("request_id")
        return {"X-Request-ID": str(request_id)} if request_id else {}

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client_cache is None:
            self._client_cache = openai.AsyncOpenAI(
                api_key="local-runtime",  # auth runtime lewat X-Runtime-Token
                base_url=self.base_url,
                http_client=self.http,
                max_retries=0,
                timeout=self.client_timeout(),
                default_headers=self.default_headers(),
            )
        return self._client_cache

    # -------------------------------------------------------------- respons
    def map_chat_response(self, data: dict[str, Any], model: ModelConfig) -> UnifiedChatResponse:
        resp = super().map_chat_response(data, model)
        resp.runtime_meta = parse_runtime_meta(data)
        return resp

    def map_chat_chunk(self, data: dict[str, Any]) -> UnifiedChunk | None:
        chunk = super().map_chat_chunk(data)
        meta = parse_runtime_meta(data)
        if meta is not None:
            chunk = chunk or UnifiedChunk()
            chunk.runtime_meta = meta
        return chunk

    def map_completion_response(
        self, data: dict[str, Any], model: ModelConfig
    ) -> UnifiedCompletionResponse:
        resp = super().map_completion_response(data, model)
        resp.runtime_meta = parse_runtime_meta(data)
        return resp

    def map_completion_chunk(self, data: dict[str, Any]) -> UnifiedChunk | None:
        chunk = super().map_completion_chunk(data)
        meta = parse_runtime_meta(data)
        if meta is not None:
            chunk = chunk or UnifiedChunk()
            chunk.runtime_meta = meta
        return chunk

    def map_embedding_response(
        self, data: dict[str, Any], model: ModelConfig
    ) -> UnifiedEmbeddingResponse:
        resp = super().map_embedding_response(data, model)
        resp.runtime_meta = parse_runtime_meta(data)
        return resp

    # ----------------------------------------------------------------- error
    def map_runtime_error(self, status: int, body: Any) -> GatewayError | None:
        err = body.get("error") if isinstance(body, dict) else None
        if not isinstance(err, dict):
            return None
        cls = RUNTIME_ERROR_CODES.get(str(err.get("code")))
        if cls is None:
            return None
        message = f"{self.cfg.code}: {err.get('message') or err.get('code')}"
        return cls(message, param=err.get("param"))

    def map_error(self, exc: Exception) -> GatewayError:
        if isinstance(exc, openai.APIStatusError):
            mapped = self.map_runtime_error(exc.status_code, exc.body)
            if mapped is None and isinstance(exc.body, dict):
                # SDK kadang sudah membuka lapisan "error"
                mapped = self.map_runtime_error(exc.status_code, {"error": exc.body})
            if mapped is not None:
                return mapped
            if exc.status_code == 401:
                self.log.error("runtime token ditolak (RUNTIME_TOKEN tidak sama?)")
        return super().map_error(exc)

    # ------------------------------------------------------------- streaming
    async def first_chunk_guard(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """Chunk pertama boleh menunggu load/swap model: LOCAL_FIRST_TOKEN_TIMEOUT_S."""
        iterator = stream.__aiter__()
        try:
            first = await asyncio.wait_for(
                iterator.__anext__(), timeout=self.settings.local_first_token_timeout_s
            )
        except StopAsyncIteration:
            return
        except TimeoutError as exc:
            limit = self.settings.local_first_token_timeout_s
            raise UpstreamTimeout(f"{self.cfg.code}: chunk pertama > {limit} detik") from exc
        yield first
        async for item in iterator:
            yield item

    # ---------------------------------------------------------------- images
    async def generate_images(
        self, model: ModelConfig, req: UnifiedImageRequest
    ) -> UnifiedImageResponse:
        body = drop_none(
            {
                "model": model.upstream_name,
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt,
                "n": req.n,
                "size": req.size,
                "steps": req.steps,
                "guidance_scale": req.guidance_scale,
                "seed": req.seed,
                "strength": req.strength,
                "image": base64.b64encode(req.image).decode() if req.image else None,
                "response_format": "b64_json",
            }
        )
        body.update(self._passthrough(req.provider_options))
        headers = {**self.default_headers(), **self.request_headers()}
        path = "edits" if req.image else "generations"
        async with self.semaphore:
            try:
                resp = await self.http.post(
                    f"{self.base_url}/images/{path}",
                    json=body,
                    headers=headers,
                    timeout=self.client_timeout(),
                )
            except httpx2.TimeoutException as exc:
                raise UpstreamTimeout(f"{self.cfg.code}: timeout image generation") from exc
            except httpx2.HTTPError as exc:
                raise self.map_error(exc) from exc
        data = _json(resp)
        if resp.status_code >= 400:
            mapped = self.map_runtime_error(resp.status_code, data)
            if mapped is not None:
                raise mapped
            if resp.status_code >= 500:
                raise ModelLoadFailed(f"{self.cfg.code}: runtime {resp.status_code}")
            raise UpstreamBadRequest(f"{self.cfg.code}: {data}")
        return self.map_image_response(data, model, req)

    def map_image_response(
        self, data: dict[str, Any], model: ModelConfig, req: UnifiedImageRequest
    ) -> UnifiedImageResponse:
        width, _, height = req.size.partition("x")
        images = []
        for i, item in enumerate(data.get("data") or []):
            png = base64.b64decode(item["b64_json"])
            images.append(
                UnifiedImage(
                    png_bytes=png,
                    sha256=hashlib.sha256(png).hexdigest(),
                    width=int(item.get("width") or width),
                    height=int(item.get("height") or height),
                    seed=int(
                        item.get("seed") if item.get("seed") is not None else (req.seed or 0) + i
                    ),
                    steps=int(item.get("steps") or req.steps or 0),
                    guidance_scale=float(item.get("guidance_scale") or req.guidance_scale or 0),
                )
            )
        return UnifiedImageResponse(
            images=images, upstream_model=model.upstream_name, runtime_meta=parse_runtime_meta(data)
        )

    async def runtime_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[int, dict[str, Any]]:
        """Panggil endpoint admin runtime (`/runtime/*`) dengan X-Runtime-Token."""
        url = self.base_url.removesuffix("/v1") + path
        resp = await self.http.request(
            method,
            url,
            params=params,
            headers={**self.default_headers(), **self.request_headers()},
            timeout=timeout,
        )
        return resp.status_code, _json(resp)

    async def loaded_aliases(self) -> set[str]:
        """Alias model yang sedang termuat di runtime (dipakai router `prefer_loaded`)."""
        url = self.base_url.removesuffix("/v1") + "/runtime/status"
        resp = await self.http.get(
            url, headers=self.default_headers(), timeout=self.settings.provider_health_timeout_s
        )
        devices = _json(resp).get("devices") or {}
        return {
            str(m.get("alias"))
            for dev in devices.values()
            if isinstance(dev, dict)
            for m in dev.get("models") or []
            if isinstance(m, dict) and m.get("alias")
        }

    # ---------------------------------------------------------------- health
    async def health(self) -> ProviderHealth:
        url = self.base_url.removesuffix("/v1") + "/health/ready"
        start = time.perf_counter()
        try:
            resp = await self.http.get(url, timeout=self.settings.provider_health_timeout_s)
        except httpx2.HTTPError as exc:
            return ProviderHealth(
                ok=False, detail=f"runtime tidak terjangkau: {type(exc).__name__}"
            )
        data = _json(resp)
        return ProviderHealth(
            ok=resp.status_code == 200 and bool(data.get("ready")),
            latency_ms=int((time.perf_counter() - start) * 1000),
            detail=None if resp.status_code == 200 else f"runtime HTTP {resp.status_code}",
            extra={k: v for k, v in data.items() if k in ("devices", "pinned", "ready")},
        )


def _json(resp: httpx2.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
