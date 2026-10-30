"""/v1/completions (raw & FIM) dengan router & fallback yang sama dengan chat (TASK-14)."""

from collections.abc import AsyncIterator

from app.schemas.catalog import ModelConfig
from app.schemas.unified import UnifiedChunk, UnifiedCompletionRequest, UnifiedCompletionResponse
from app.services.chat_service import stream_with_fallback
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router


def _clamp(
    ctx: RequestCtx, req: UnifiedCompletionRequest, model: ModelConfig
) -> UnifiedCompletionRequest:
    limit = model.max_output_tokens
    if req.max_tokens is not None and limit and req.max_tokens > limit:
        if "max_tokens_clamped" not in ctx.warnings:
            ctx.warnings.append("max_tokens_clamped")
        return req.model_copy(update={"max_tokens": limit})
    return req


class CompletionService:
    def __init__(self, router: Router) -> None:
        self.router = router

    async def execute(
        self, ctx: RequestCtx, req: UnifiedCompletionRequest, candidates: list[ModelConfig]
    ) -> tuple[UnifiedCompletionResponse, Outcome]:
        resp, _ = await self.router.run_with_fallback(
            ctx, candidates, lambda p, m: p.completion(m, _clamp(ctx, req, m))
        )
        return resp, Outcome(
            usage=resp.usage,
            finish_reason=resp.finish_reason,
            upstream_model=resp.upstream_model,
            runtime_meta=resp.runtime_meta,
            response_body={"text": resp.text},
        )

    def execute_stream(
        self,
        ctx: RequestCtx,
        req: UnifiedCompletionRequest,
        candidates: list[ModelConfig],
        outcome: Outcome,
    ) -> AsyncIterator[UnifiedChunk]:
        return stream_with_fallback(
            self.router,
            ctx,
            candidates,
            lambda p, m: p.completion_stream(m, _clamp(ctx, req, m)),
            outcome,
        )
