"""Kontrak tunggal semua provider adapter (remote & lokal)."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar

import httpx2

from app.schemas.catalog import ModelConfig, ProviderConfig
from app.schemas.unified import (
    ProviderHealth,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedCompletionRequest,
    UnifiedCompletionResponse,
    UnifiedEmbeddingResponse,
    UnifiedImageRequest,
    UnifiedImageResponse,
)
from app.utils.errors import CapabilityNotSupported
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings


class BaseProvider(ABC):
    """`http` adalah klien httpx2 bersama (SDK openai/anthropic memakai httpx2).

    Setiap adapter wajib memetakan error native → UpstreamTimeout / UpstreamRateLimited /
    UpstreamError / UpstreamBadRequest (PRD §8.1 langkah 7)."""

    code: ClassVar[str]

    def __init__(self, cfg: ProviderConfig, http: httpx2.AsyncClient, settings: "Settings"):
        self.cfg = cfg
        self.http = http
        self.settings = settings
        self.semaphore = asyncio.Semaphore(max(1, cfg.max_concurrency))
        self.log = get_logger(f"provider.{cfg.code}")

    @property
    def api_key(self) -> str | None:
        return self.settings.provider_secret(self.cfg.api_key_env)

    async def startup(self) -> None:  # noqa: B027 - opsional
        """Opsional (mis. warmup)."""

    async def shutdown(self) -> None:  # noqa: B027 - opsional
        """Opsional (tutup klien)."""

    async def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="no health check")

    # ------------------------------------------------------------------ chat
    @abstractmethod
    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse: ...

    @abstractmethod
    def chat_stream(
        self, model: ModelConfig, req: UnifiedChatRequest
    ) -> AsyncIterator[UnifiedChunk]: ...

    # ------------------------------------------------------- opsional/kapabilitas
    async def completion(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> UnifiedCompletionResponse:
        raise CapabilityNotSupported(f"Provider {self.cfg.code} tidak mendukung completions")

    def completion_stream(
        self, model: ModelConfig, req: UnifiedCompletionRequest
    ) -> AsyncIterator[UnifiedChunk]:
        raise CapabilityNotSupported(f"Provider {self.cfg.code} tidak mendukung completions")

    async def embed(
        self,
        model: ModelConfig,
        inputs: list[str],
        dimensions: int | None,
        provider_options: dict[str, Any],
    ) -> UnifiedEmbeddingResponse:
        raise CapabilityNotSupported(f"Provider {self.cfg.code} tidak mendukung embeddings")

    async def generate_images(
        self, model: ModelConfig, req: UnifiedImageRequest
    ) -> UnifiedImageResponse:
        raise CapabilityNotSupported(f"Provider {self.cfg.code} tidak mendukung image generation")


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    """Buang key bernilai None (gateway tidak mengirim parameter yang tidak diisi caller)."""
    return {k: v for k, v in data.items() if v is not None}
