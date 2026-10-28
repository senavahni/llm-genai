"""Provider palsu untuk test: bisa disetel sukses / gagal / gagal di tengah stream / lambat."""

import asyncio
import hashlib
import io
from collections.abc import AsyncIterator
from typing import Any, ClassVar, Literal

import httpx2

from app.core.config import Settings
from app.schemas.catalog import ModelConfig, ProviderConfig
from app.schemas.unified import (
    RuntimeMeta,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedCompletionRequest,
    UnifiedCompletionResponse,
    UnifiedEmbeddingResponse,
    UnifiedImage,
    UnifiedImageRequest,
    UnifiedImageResponse,
    Usage,
)
from app.services.providers.base import BaseProvider
from app.utils.errors import UpstreamError

Mode = Literal["ok", "fail", "fail_mid", "slow"]


class FakeProvider(BaseProvider):
    code: ClassVar[str] = "fake"

    def __init__(
        self,
        cfg: ProviderConfig,
        http: httpx2.AsyncClient,
        settings: Settings,
        *,
        mode: Mode = "ok",
        chunks: list[str] | None = None,
        delay_s: float = 0.0,
        error: Exception | None = None,
        runtime_meta: RuntimeMeta | None = None,
    ) -> None:
        super().__init__(cfg, http, settings)
        self.mode = mode
        self.chunks = chunks or ["Hel", "lo", "!"]
        self.delay_s = delay_s
        self.error = error  # dilempar pada mode "fail" (default UpstreamError)
        self.runtime_meta = runtime_meta
        self.calls = 0
        self.requests: list[Any] = []
        self.closed = False

    def _fail(self, message: str) -> Exception:
        return self.error or UpstreamError(message)

    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse:
        self.calls += 1
        self.requests.append(req)
        if self.mode == "fail":
            raise self._fail("fake failure")
        if self.mode == "slow":
            await asyncio.sleep(self.delay_s)
        return UnifiedChatResponse(
            content="".join(self.chunks),
            finish_reason="stop",
            usage=Usage(prompt_tokens=3, completion_tokens=len(self.chunks)),
            upstream_model=model.upstream_name,
            runtime_meta=self.runtime_meta,
        )

    async def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]:
        self.calls += 1
        self.requests.append(req)
        if self.mode == "fail":
            raise self._fail("fake failure before first chunk")
        try:
            for i, text in enumerate(self.chunks):
                if self.mode == "slow":
                    await asyncio.sleep(self.delay_s)
                if self.mode == "fail_mid" and i == 1:
                    raise UpstreamError("fake failure mid-stream")
                yield UnifiedChunk(delta_content=text)
            yield UnifiedChunk(
                finish_reason="stop",
                usage=Usage(prompt_tokens=3, completion_tokens=len(self.chunks)),
                runtime_meta=self.runtime_meta,
            )
        finally:
            self.closed = True

    # ------------------------------------------------------- completion / FIM
    def _completion_text(self, req: UnifiedCompletionRequest) -> str:
        return "    return n > 1" if req.suffix is not None else " lanjutan"

    async def completion(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> UnifiedCompletionResponse:
        self.calls += 1
        self.requests.append(req)
        if self.mode == "fail":
            raise self._fail("fake failure")
        return UnifiedCompletionResponse(
            text=self._completion_text(req),
            finish_reason="stop",
            usage=Usage(prompt_tokens=5, completion_tokens=4),
            upstream_model=model.upstream_name,
            runtime_meta=self.runtime_meta,
        )

    async def completion_stream(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> AsyncIterator[UnifiedChunk]:
        self.calls += 1
        self.requests.append(req)
        if self.mode == "fail":
            raise self._fail("fake failure")
        text = self._completion_text(req)
        for piece in (text[:6], text[6:]):
            yield UnifiedChunk(delta_content=piece)
        yield UnifiedChunk(
            finish_reason="stop",
            usage=Usage(prompt_tokens=5, completion_tokens=4),
            runtime_meta=self.runtime_meta,
        )

    # -------------------------------------------------------------- embeddings
    async def embed(
        self,
        model: ModelConfig,
        inputs: list[str],
        dimensions: int | None,
        provider_options: dict[str, Any],
    ) -> UnifiedEmbeddingResponse:
        self.calls += 1
        self.requests.append({"inputs": inputs, "dimensions": dimensions, **provider_options})
        return UnifiedEmbeddingResponse(
            vectors=[[0.5, -1.25, float(i)] for i in range(len(inputs))],
            usage=Usage(prompt_tokens=len(inputs) * 2),
            upstream_model=model.upstream_name,
        )

    # ------------------------------------------------------------------ images
    async def generate_images(
        self, model: ModelConfig, req: UnifiedImageRequest
    ) -> UnifiedImageResponse:
        self.calls += 1
        self.requests.append(req)
        if self.mode == "fail":
            raise self._fail("fake failure")
        seed = req.seed if req.seed is not None else 1
        images = []
        for i in range(req.n):
            png = _png((seed + i) % 256)
            images.append(
                UnifiedImage(
                    png_bytes=png,
                    sha256=hashlib.sha256(png).hexdigest(),
                    width=512,
                    height=512,
                    seed=seed + i,
                    steps=req.steps or 25,
                    guidance_scale=7.5,
                )
            )
        return UnifiedImageResponse(
            images=images, upstream_model=model.upstream_name, runtime_meta=self.runtime_meta
        )


def _png(value: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (value, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()
