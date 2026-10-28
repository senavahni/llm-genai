"""Eksekusi chat dengan fallback (TASK-13). Non-stream: fallback antar kandidat untuk error
retryable. Stream: fallback hanya sebelum chunk pertama; setelah chunk pertama keluar ke caller
error diteruskan apa adanya."""

import asyncio
from collections.abc import AsyncIterator

from app.schemas.catalog import ModelConfig
from app.schemas.unified import UnifiedChatRequest, UnifiedChatResponse, UnifiedChunk
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router, aclose_quietly
from app.utils.errors import GatewayError, InvalidRequestError, UpstreamError


def clamp_max_tokens(
    ctx: RequestCtx, req: UnifiedChatRequest, model: ModelConfig
) -> UnifiedChatRequest:
    """max_tokens > batas model → dipotong + header X-Gateway-Warning (bukan error)."""
    limit = model.max_output_tokens
    if req.max_tokens is not None and limit and req.max_tokens > limit:
        if "max_tokens_clamped" not in ctx.warnings:
            ctx.warnings.append("max_tokens_clamped")
        return req.model_copy(update={"max_tokens": limit})
    return req


def absorb_chunk(outcome: Outcome, chunk: UnifiedChunk) -> None:
    """Kumpulkan usage/finish/runtime_meta & isi respons (untuk log payload) dari chunk."""
    if chunk.usage is not None:
        outcome.usage = chunk.usage
    if chunk.finish_reason:
        outcome.finish_reason = chunk.finish_reason
    if chunk.runtime_meta is not None:
        outcome.runtime_meta = chunk.runtime_meta
    if chunk.upstream_model:
        outcome.upstream_model = chunk.upstream_model
    body = outcome.response_body if outcome.response_body is not None else {}
    if chunk.delta_content:
        body["content"] = body.get("content", "") + chunk.delta_content
    for call in chunk.delta_tool_calls or []:
        calls = body.setdefault("tool_calls", {})
        entry = calls.setdefault(str(call.index), {"id": None, "name": "", "arguments": ""})
        entry["id"] = call.id or entry["id"]
        entry["name"] += call.name or ""
        entry["arguments"] += call.arguments or ""
    outcome.response_body = body or None


class ChatService:
    def __init__(self, router: Router) -> None:
        self.router = router

    @staticmethod
    def validate(req: UnifiedChatRequest) -> None:
        if not req.messages:
            raise InvalidRequestError("messages tidak boleh kosong", param="messages")

    async def execute(
        self, ctx: RequestCtx, req: UnifiedChatRequest, candidates: list[ModelConfig]
    ) -> tuple[UnifiedChatResponse, Outcome]:
        self.validate(req)
        resp, _model = await self.router.run_with_fallback(
            ctx, candidates, lambda p, m: p.chat(m, clamp_max_tokens(ctx, req, m))
        )
        outcome = Outcome(
            usage=resp.usage,
            finish_reason=resp.finish_reason,
            upstream_model=resp.upstream_model,
            runtime_meta=resp.runtime_meta,
            response_body={
                "content": resp.content,
                "tool_calls": [c.model_dump() for c in resp.tool_calls or []] or None,
            },
        )
        return resp, outcome

    async def execute_stream(
        self,
        ctx: RequestCtx,
        req: UnifiedChatRequest,
        candidates: list[ModelConfig],
        outcome: Outcome,
    ) -> AsyncIterator[UnifiedChunk]:
        """Async generator: kandidat dipilih saat chunk pertama diminta (controller menunggu
        chunk pertama sebelum mengirim header), sehingga error sebelum token pertama tetap
        menjadi status HTTP yang benar."""
        self.validate(req)
        model, first, iterator, started = await self.router.open_stream(
            ctx, candidates, lambda p, m: p.chat_stream(m, clamp_max_tokens(ctx, req, m))
        )
        outcome.ttft_ms = ctx.elapsed_ms
        status, error = "success", None
        try:
            if first is not None:
                absorb_chunk(outcome, first)
                yield first
            async for chunk in iterator:
                absorb_chunk(outcome, chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            status = "cancelled"
            raise
        except GatewayError as exc:
            status, error = "error", exc
            raise
        except Exception as exc:
            status, error = "error", UpstreamError(f"{model.alias}: {type(exc).__name__}: {exc}")
            raise error from exc
        finally:
            await aclose_quietly(iterator)
            ctx.record(model, status, started, error=error, runtime_meta=outcome.runtime_meta)
            if status == "success":
                self.router.breaker.record_success(model.alias)
