"""Provider palsu untuk test: bisa disetel sukses / gagal / gagal di tengah stream / lambat."""

import asyncio
from collections.abc import AsyncIterator
from typing import ClassVar, Literal

import httpx2

from app.core.config import Settings
from app.schemas.catalog import ModelConfig, ProviderConfig
from app.schemas.unified import (
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
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
    ) -> None:
        super().__init__(cfg, http, settings)
        self.mode = mode
        self.chunks = chunks or ["Hel", "lo", "!"]
        self.delay_s = delay_s
        self.calls = 0
        self.closed = False

    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse:
        self.calls += 1
        if self.mode == "fail":
            raise UpstreamError("fake failure")
        if self.mode == "slow":
            await asyncio.sleep(self.delay_s)
        return UnifiedChatResponse(
            content="".join(self.chunks),
            finish_reason="stop",
            usage=Usage(prompt_tokens=3, completion_tokens=len(self.chunks)),
            upstream_model=model.upstream_name,
        )

    async def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]:
        self.calls += 1
        if self.mode == "fail":
            raise UpstreamError("fake failure before first chunk")
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
            )
        finally:
            self.closed = True
