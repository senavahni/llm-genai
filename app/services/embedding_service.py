"""/v1/embeddings dengan router & fallback (TASK-14). Embedding lokal tidak ada lagi
(keputusan 28 Okt 2026), jadi praktis remote; input token-ID hanya untuk model remote."""

from typing import Any

from app.schemas.catalog import ModelConfig
from app.schemas.unified import UnifiedEmbeddingResponse
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router
from app.utils.errors import InvalidRequestError

MAX_INPUTS = 2048


def normalize_input(raw: Any) -> list[Any]:
    """str | list[str] | list[int] | list[list[int]] → daftar item (teks atau list token)."""
    if isinstance(raw, str):
        items: list[Any] = [raw]
    elif isinstance(raw, list) and raw and all(isinstance(x, int) for x in raw):
        items = [raw]  # satu input berupa token ID
    elif isinstance(raw, list):
        items = list(raw)
    else:
        raise InvalidRequestError("input tidak valid", param="input")
    if not items:
        raise InvalidRequestError("input tidak boleh kosong", param="input")
    if len(items) > MAX_INPUTS:
        raise InvalidRequestError(f"Maksimal {MAX_INPUTS} input per request", param="input")
    return items


class EmbeddingService:
    def __init__(self, router: Router) -> None:
        self.router = router

    async def execute(
        self,
        ctx: RequestCtx,
        inputs: list[Any],
        dimensions: int | None,
        provider_options: dict[str, Any],
        candidates: list[ModelConfig],
    ) -> tuple[UnifiedEmbeddingResponse, Outcome]:
        has_token_ids = any(not isinstance(x, str) for x in inputs)

        async def call(provider: Any, model: ModelConfig) -> UnifiedEmbeddingResponse:
            if has_token_ids and model.is_local:
                raise InvalidRequestError(
                    "Input token-ID hanya didukung model remote", param="input"
                )
            result: UnifiedEmbeddingResponse = await provider.embed(
                model, inputs, dimensions, provider_options
            )
            return result

        resp, _ = await self.router.run_with_fallback(ctx, candidates, call)
        return resp, Outcome(
            usage=resp.usage, upstream_model=resp.upstream_model, runtime_meta=resp.runtime_meta
        )
