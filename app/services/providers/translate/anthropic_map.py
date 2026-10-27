"""Translasi format OpenAI (unified) ↔ Anthropic Messages API. Murni dict → mudah diuji."""

from dataclasses import dataclass, field
from typing import Any

from app.schemas.catalog import ModelConfig
from app.schemas.unified import (
    FunctionCall,
    ImagePart,
    TextPart,
    ToolCall,
    ToolCallDelta,
    UnifiedChatRequest,
    UnifiedChatResponse,
    UnifiedChunk,
    UnifiedMessage,
    Usage,
)
from app.services.providers.translate.common import (
    dumps_arguments,
    loads_arguments,
    parse_image_url,
)
from app.utils.errors import UpstreamError

DEFAULT_MAX_TOKENS = 4096
GATEWAY_ONLY_OPTIONS = frozenset({"include_reasoning"})

STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "content_filter",
}


@dataclass(frozen=True, slots=True)
class AnthropicPayload:
    payload: dict[str, Any]
    prefill: str | None = None  # teks prefill assistant yang harus diprepend ke output


# ---------------------------------------------------------------- request
def _content_blocks(msg: UnifiedMessage) -> list[dict[str, Any]]:
    if msg.content is None:
        return []
    if isinstance(msg.content, str):
        return [{"type": "text", "text": msg.content}] if msg.content else []
    blocks: list[dict[str, Any]] = []
    for part in msg.content:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            img = parse_image_url(part.image_url.url)
            source: dict[str, Any]
            if img.data_b64 is not None:
                source = {"type": "base64", "media_type": img.mime_type, "data": img.data_b64}
            else:
                source = {"type": "url", "url": img.url}
            blocks.append({"type": "image", "source": source})
    return blocks


def _to_blocks(msg: UnifiedMessage) -> tuple[str, list[dict[str, Any]]]:
    if msg.role == "tool":
        return "user", [
            {"type": "tool_result", "tool_use_id": msg.tool_call_id or "", "content": msg.text()}
        ]
    role = "assistant" if msg.role == "assistant" else "user"
    blocks = _content_blocks(msg)
    for tc in msg.tool_calls or []:
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": loads_arguments(tc.function.arguments),
            }
        )
    return role, blocks


def _simplify(blocks: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    if len(blocks) == 1 and blocks[0]["type"] == "text":
        return str(blocks[0]["text"])
    return blocks


def build_messages(messages: list[UnifiedMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    """Kembalikan (system, messages). System (bisa >1) digabung; role berurutan sama digabung
    (Anthropic mensyaratkan alternasi user/assistant); tool result berurutan → satu user message."""
    system_parts = [m.text() for m in messages if m.role in ("system", "developer")]
    merged: list[tuple[str, list[dict[str, Any]]]] = []
    for msg in messages:
        if msg.role in ("system", "developer"):
            continue
        role, blocks = _to_blocks(msg)
        if not blocks:
            continue
        if merged and merged[-1][0] == role:
            merged[-1][1].extend(blocks)
        else:
            merged.append((role, blocks))
    out = [{"role": role, "content": _simplify(blocks)} for role, blocks in merged]
    system = "\n\n".join(p for p in system_parts if p) or None
    return system, out


def map_tool_choice(tool_choice: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return {
            "auto": {"type": "auto"},
            "required": {"type": "any"},
            "none": {"type": "none"},
        }.get(tool_choice, {"type": "auto"})
    name = (tool_choice.get("function") or {}).get("name") or tool_choice.get("name")
    if name:
        return {"type": "tool", "name": name}
    return {"type": "auto"}


def build_payload(model: ModelConfig, req: UnifiedChatRequest) -> AnthropicPayload:
    system, messages = build_messages(req.messages)
    prefill: str | None = None
    rf_type = (req.response_format or {}).get("type")
    if rf_type in ("json_object", "json_schema") and (
        model.config.get("json_mode_strategy") == "prefill"
    ):
        prefill = "{"
        messages.append({"role": "assistant", "content": prefill})

    payload: dict[str, Any] = {
        "model": model.upstream_name,
        "messages": messages,
        "max_tokens": req.max_tokens or model.max_output_tokens or DEFAULT_MAX_TOKENS,
    }
    optional = {
        "system": system,
        "temperature": req.temperature,
        "top_p": req.top_p,
        "stop_sequences": req.stop,
        "tools": [
            {
                "name": t.function.name,
                "description": t.function.description,
                "input_schema": t.function.parameters or {"type": "object", "properties": {}},
            }
            for t in req.tools
        ]
        if req.tools
        else None,
        "tool_choice": map_tool_choice(req.tool_choice) if req.tools else None,
    }
    for k, v in optional.items():
        if v is not None:
            payload[k] = v
    for tool in payload.get("tools", []):
        if tool["description"] is None:
            del tool["description"]
    payload.update({k: v for k, v in req.provider_options.items() if k not in GATEWAY_ONLY_OPTIONS})
    return AnthropicPayload(payload=payload, prefill=prefill)


# --------------------------------------------------------------- response
def parse_usage(usage: dict[str, Any] | None) -> Usage:
    usage = usage or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    return Usage(
        prompt_tokens=(usage.get("input_tokens") or 0) + cache_read + cache_write,
        completion_tokens=usage.get("output_tokens") or 0,
        cached_tokens=cache_read,
    )


def parse_response(
    data: dict[str, Any],
    *,
    include_reasoning: bool = False,
    prefill: str | None = None,
) -> UnifiedChatResponse:
    texts: list[str] = []
    thinking: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in data.get("content") or []:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text") or "")
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.get("id") or "",
                    function=FunctionCall(
                        name=block.get("name") or "", arguments=dumps_arguments(block.get("input"))
                    ),
                )
            )
        elif btype == "thinking":
            thinking.append(block.get("thinking") or "")
    content = "".join(texts) if texts else None
    if prefill and content is not None:
        content = prefill + content
    return UnifiedChatResponse(
        content=content,
        tool_calls=tool_calls or None,
        finish_reason=STOP_REASON_MAP.get(data.get("stop_reason") or "", data.get("stop_reason")),
        usage=parse_usage(data.get("usage")),
        upstream_model=data.get("model") or "",
        raw_id=data.get("id"),
        reasoning_content="".join(thinking) if include_reasoning and thinking else None,
    )


# -------------------------------------------------------------- streaming
@dataclass
class StreamTranslator:
    """Event stream Anthropic → UnifiedChunk. Index tool call OpenAI = urutan blok tool_use."""

    include_reasoning: bool = False
    prefill: str | None = None
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    raw_id: str | None = None
    finish_reason: str | None = None
    _tool_index: dict[int, int] = field(default_factory=dict)
    _emitted: bool = False

    @property
    def started(self) -> bool:
        return self._emitted

    def feed(self, event: dict[str, Any]) -> list[UnifiedChunk]:
        etype = event.get("type")
        out: list[UnifiedChunk] = []
        if etype == "message_start":
            msg = event.get("message") or {}
            self.model = msg.get("model")
            self.raw_id = msg.get("id")
            self.usage = parse_usage(msg.get("usage"))
            if self.prefill:
                out.append(UnifiedChunk(delta_content=self.prefill))
        elif etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                idx = len(self._tool_index)
                self._tool_index[event.get("index", 0)] = idx
                out.append(
                    UnifiedChunk(
                        delta_tool_calls=[
                            ToolCallDelta(
                                index=idx, id=block.get("id"), name=block.get("name"), arguments=""
                            )
                        ]
                    )
                )
        elif etype == "content_block_delta":
            delta = event.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                out.append(UnifiedChunk(delta_content=delta.get("text") or ""))
            elif dtype == "input_json_delta":
                idx = self._tool_index.get(event.get("index", 0), 0)
                out.append(
                    UnifiedChunk(
                        delta_tool_calls=[
                            ToolCallDelta(index=idx, arguments=delta.get("partial_json") or "")
                        ]
                    )
                )
            elif dtype == "thinking_delta" and self.include_reasoning:
                out.append(UnifiedChunk(delta_reasoning=delta.get("thinking") or ""))
        elif etype == "message_delta":
            delta = event.get("delta") or {}
            reason = delta.get("stop_reason")
            if reason:
                self.finish_reason = STOP_REASON_MAP.get(reason, reason)
            usage = event.get("usage") or {}
            if usage.get("output_tokens") is not None:
                self.usage.completion_tokens = usage["output_tokens"]
            if usage.get("input_tokens") is not None:  # beberapa versi API mengirim ulang
                merged = parse_usage({**usage, "output_tokens": self.usage.completion_tokens})
                if merged.prompt_tokens:
                    self.usage = merged
        elif etype == "message_stop":
            out.append(
                UnifiedChunk(
                    finish_reason=self.finish_reason or "stop",
                    usage=self.usage,
                    upstream_model=self.model,
                    raw_id=self.raw_id,
                )
            )
        elif etype == "error":
            err = event.get("error") or {}
            raise UpstreamError(
                f"anthropic stream error: {err.get('type', 'error')}: {err.get('message', '')}"
            )
        if out:
            self._emitted = True
        return out
