"""/v1/embeddings dengan router & fallback (TASK-14). Embedding lokal = Qwen3-Embedding di GPU
lewat Local Runtime (route `embed-local`, LGW-V1-02); input token-ID hanya untuk model remote.

LGW-V1-04 (opsi khusus gateway, tidak diteruskan apa adanya ke provider):
- `provider_options.input_type` ∈ {query, document}: prefix dari config model
  `embedding_instructions` diterapkan per kandidat (default document = tanpa prefix);
- `provider_options.truncate=true`: input > max_input_tokens dipotong runtime (+ warning);
- header `X-Priority: interactive|bulk` → antrean prioritas runtime."""

from typing import Any

from app.schemas.catalog import ModelConfig
from app.schemas.unified import UnifiedEmbeddingResponse
from app.services.context import Outcome, RequestCtx
from app.services.router_service import Router
from app.utils.errors import InvalidRequestError

MAX_INPUTS = 2048
INPUT_TYPES = ("query", "document")
PRIORITIES = ("interactive", "bulk")
# opsi yang diolah gateway; tidak dikirim mentah ke provider
GATEWAY_EMBED_OPTIONS = frozenset({"input_type", "truncate"})


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


def parse_priority(raw: str | None) -> str:
    value = (raw or "interactive").strip().lower()
    if value not in PRIORITIES:
        raise InvalidRequestError("X-Priority harus interactive atau bulk", param="X-Priority")
    return value


def input_type_of(options: dict[str, Any]) -> str:
    value = options.get("input_type") or "document"
    if value not in INPUT_TYPES:
        raise InvalidRequestError(
            "provider_options.input_type harus query atau document", param="input_type"
        )
    return str(value)


def apply_instruction(model: ModelConfig, inputs: list[Any], input_type: str) -> list[Any]:
    """Prefix instruksi model (mis. Qwen3: 'Instruct: …\\nQuery: ' hanya untuk query)."""
    prefix = (model.config.get("embedding_instructions") or {}).get(input_type) or ""
    if not prefix:
        return inputs
    return [prefix + x if isinstance(x, str) else x for x in inputs]


def options_for(model: ModelConfig, options: dict[str, Any], priority: str) -> dict[str, Any]:
    out = {k: v for k, v in options.items() if k not in GATEWAY_EMBED_OPTIONS}
    if model.is_local:  # runtime lokal memahami truncate & priority
        out["priority"] = priority
        if options.get("truncate") is True:
            out["truncate"] = True
    return out


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
        priority: str = "interactive",
    ) -> tuple[UnifiedEmbeddingResponse, Outcome]:
        has_token_ids = any(not isinstance(x, str) for x in inputs)
        input_type = input_type_of(provider_options)

        async def call(provider: Any, model: ModelConfig) -> UnifiedEmbeddingResponse:
            if has_token_ids and model.is_local:
                raise InvalidRequestError(
                    "Input token-ID hanya didukung model remote", param="input"
                )
            result: UnifiedEmbeddingResponse = await provider.embed(
                model,
                apply_instruction(model, inputs, input_type),
                dimensions,
                options_for(model, provider_options, priority),
            )
            return result

        resp, _ = await self.router.run_with_fallback(ctx, candidates, call)
        if resp.runtime_meta is not None:
            ctx.warnings += resp.runtime_meta.warnings  # mis. input_truncated:N → header
        return resp, Outcome(
            usage=resp.usage, upstream_model=resp.upstream_model, runtime_meta=resp.runtime_meta
        )
