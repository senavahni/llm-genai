"""Konversi request/response publik OpenAI ↔ schema unified (TASK-14)."""

import base64
import struct
import time
from typing import Any

from pydantic import ValidationError

from app.schemas.catalog import ModelConfig, RouteConfig
from app.schemas.images import ImageGenerationRequest
from app.schemas.openai_compat import ChatCompletionRequest, CompletionRequest
from app.schemas.unified import (
    ToolDef,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedCompletionRequest,
    UnifiedCompletionResponse,
    UnifiedImageRequest,
    UnifiedImageResponse,
    UnifiedMessage,
    Usage,
)
from app.services.router_service import Capabilities
from app.utils.errors import InvalidRequestError, UnsupportedParameter


def _stop(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


def _single(n: int | None) -> None:
    if n not in (None, 1):
        raise UnsupportedParameter("Hanya n=1 yang didukung gateway", param="n")


# ------------------------------------------------------------------ chat
def chat_to_unified(body: ChatCompletionRequest) -> UnifiedChatRequest:
    _single(body.n)
    if not body.messages:
        raise InvalidRequestError("messages tidak boleh kosong", param="messages")
    try:
        messages = [UnifiedMessage.model_validate(m) for m in body.messages]
        tools = [ToolDef.model_validate(t) for t in body.tools] if body.tools else None
        return UnifiedChatRequest(
            messages=messages,
            tools=tools,
            tool_choice=body.tool_choice,
            response_format=body.response_format,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_completion_tokens or body.max_tokens,
            stop=_stop(body.stop),
            seed=body.seed,
            stream=body.stream,
            provider_options=body.provider_options(),
            user=body.user,
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        raise InvalidRequestError(f"messages/tools tidak valid: {loc}: {first['msg']}") from exc


def chat_capabilities(req: UnifiedChatRequest) -> Capabilities:
    vision = any(
        isinstance(m.content, list) and any(p.type == "image_url" for p in m.content)
        for m in req.messages
    )
    rf_type = (req.response_format or {}).get("type")
    return Capabilities(
        model_type="chat",
        tools=bool(req.tools),
        vision=vision,
        json=rf_type in ("json_object", "json_schema"),
        stream=req.stream,
    )


def _usage_dict(usage: Usage) -> dict[str, Any]:
    out: dict[str, Any] = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    if usage.cached_tokens:
        out["prompt_tokens_details"] = {"cached_tokens": usage.cached_tokens}
    return out


def chat_response(resp: UnifiedChatResponse, request_id: str, model: str) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": resp.content}
    if resp.tool_calls:
        message["tool_calls"] = [c.model_dump() for c in resp.tool_calls]
    if resp.reasoning_content:
        message["reasoning_content"] = resp.reasoning_content
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,  # alias yang diminta caller
        "choices": [{"index": 0, "message": message, "finish_reason": resp.finish_reason}],
        "usage": _usage_dict(resp.usage),
        "system_fingerprint": None,
    }


def chat_chunk(chunk: UnifiedChunk, request_id: str, model: str, created: int) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if chunk.delta_content is not None:
        delta["content"] = chunk.delta_content
    if chunk.delta_reasoning is not None:
        delta["reasoning_content"] = chunk.delta_reasoning
    if chunk.delta_tool_calls:
        delta["tool_calls"] = [
            {
                "index": t.index,
                **({"id": t.id, "type": "function"} if t.id else {}),
                "function": {
                    k: v for k, v in (("name", t.name), ("arguments", t.arguments)) if v is not None
                },
            }
            for t in chunk.delta_tool_calls
        ]
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "system_fingerprint": None,
        "choices": [{"index": 0, "delta": delta, "finish_reason": chunk.finish_reason}],
    }


def usage_chunk(usage: Usage, request_id: str, model: str, created: int, *, chat: bool = True):
    return {
        "id": f"{'chatcmpl' if chat else 'cmpl'}-{request_id}",
        "object": "chat.completion.chunk" if chat else "text_completion",
        "created": created,
        "model": model,
        "choices": [],
        "usage": _usage_dict(usage),
    }


# ------------------------------------------------------------ completions
def completion_to_unified(body: CompletionRequest) -> UnifiedCompletionRequest:
    _single(body.n)
    if not isinstance(body.prompt, str):
        raise InvalidRequestError("prompt berupa list belum didukung (v1)", param="prompt")
    if body.echo:
        raise UnsupportedParameter("echo tidak didukung", param="echo")
    return UnifiedCompletionRequest(
        prompt=body.prompt,
        suffix=body.suffix,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        top_p=body.top_p,
        stop=_stop(body.stop),
        seed=body.seed,
        stream=body.stream,
        provider_options=body.provider_options(),
    )


def completion_capabilities(req: UnifiedCompletionRequest) -> Capabilities:
    return Capabilities(model_type="completion", fim=req.suffix is not None, stream=req.stream)


def completion_response(
    resp: UnifiedCompletionResponse, request_id: str, model: str
) -> dict[str, Any]:
    return {
        "id": f"cmpl-{request_id}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {"index": 0, "text": resp.text, "finish_reason": resp.finish_reason, "logprobs": None}
        ],
        "usage": _usage_dict(resp.usage),
    }


def completion_chunk(
    chunk: UnifiedChunk, request_id: str, model: str, created: int
) -> dict[str, Any]:
    return {
        "id": f"cmpl-{request_id}",
        "object": "text_completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "text": chunk.delta_content or "",
                "finish_reason": chunk.finish_reason,
                "logprobs": None,
            }
        ],
    }


# ------------------------------------------------------------- embeddings
def embedding_vector(vector: list[float], encoding: str) -> list[float] | str:
    if encoding == "base64":
        # float32 little-endian, sama dengan format OpenAI (didekode SDK resmi)
        return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()
    return vector


# ------------------------------------------------------------------ images
def image_to_unified(
    body: ImageGenerationRequest, image: bytes | None = None, strength: float | None = None
) -> UnifiedImageRequest:
    return UnifiedImageRequest(
        prompt=body.prompt,
        negative_prompt=body.negative_prompt,
        n=body.n,
        size=body.size,
        steps=body.steps,
        guidance_scale=body.guidance_scale,
        seed=body.seed,
        image=image,
        strength=strength,
        provider_options=body.provider_options(),
    )


def image_meta(img: Any) -> dict[str, Any]:
    return {
        "seed": img.seed,
        "steps": img.steps,
        "guidance_scale": img.guidance_scale,
        "width": img.width,
        "height": img.height,
    }


def image_response(result: UnifiedImageResponse, urls: list[str] | None) -> dict[str, Any]:
    data = []
    for i, img in enumerate(result.images):
        item: dict[str, Any] = (
            {"url": urls[i]} if urls else {"b64_json": base64.b64encode(img.png_bytes).decode()}
        )
        item["revised_prompt"] = None
        item["x_meta"] = image_meta(img)
        data.append(item)
    return {"created": int(time.time()), "data": data}


# ------------------------------------------------------------------ models
def _capabilities(models: list[ModelConfig]) -> dict[str, bool]:
    return {
        "tools": any(m.supports_tools for m in models),
        "vision": any(m.supports_vision for m in models),
        "json": any(m.supports_json_mode for m in models),
        "fim": any(m.supports_fim for m in models),
        "image": any(m.model_type == "image" for m in models),
        "image_edit": any("image-to-image" in (m.config.get("tasks") or ()) for m in models),
        "embedding": any(m.model_type == "embedding" for m in models),
    }


def model_object(model: ModelConfig) -> dict[str, Any]:
    return {
        "id": model.alias,
        "object": "model",
        "created": 0,
        "owned_by": model.provider_code,
        "x_capabilities": _capabilities([model]),
        "x_tier": model.tier,
        "x_device": model.device,
        "x_type": model.model_type,
    }


def route_object(route: RouteConfig, targets: list[ModelConfig]) -> dict[str, Any]:
    devices = sorted({m.device for m in targets})
    return {
        "id": route.alias,
        "object": "model",
        "created": 0,
        "owned_by": "gateway-route",
        "x_capabilities": _capabilities(targets),
        "x_tier": targets[0].tier if targets else None,
        "x_device": devices[0] if len(devices) == 1 else devices,
        "x_targets": [m.alias for m in targets],
        "description": route.description,
    }
