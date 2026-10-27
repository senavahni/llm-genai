"""Translasi format OpenAI (unified) ↔ Gemini (google-genai). Murni dict (snake_case, sesuai
model pydantic google-genai) → mudah diuji tanpa jaringan.

Gemini tidak selalu memberi id tool call → dibuat `call_<uuid8>`. Model Gemini terbaru
mewajibkan `thought_signature` dikirim kembali bersama function_call di giliran berikutnya;
karena gateway stateless, signature disisipkan di id tool call (`call_x.ts.<base64>`) dan
diekstrak lagi saat caller mengirim riwayat."""

import base64
import json
import uuid
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

GATEWAY_ONLY_OPTIONS = frozenset({"include_reasoning"})
_SIG_SEP = ".ts."
_UNSUPPORTED_SCHEMA_KEYS = frozenset({"$schema", "$id", "strict"})

FINISH_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
}


def new_call_id(signature: str | None = None) -> str:
    base = f"call_{uuid.uuid4().hex[:8]}"
    return f"{base}{_SIG_SEP}{signature}" if signature else base


def split_call_id(call_id: str) -> tuple[str, str | None]:
    base, sep, sig = call_id.partition(_SIG_SEP)
    return base, (sig if sep else None)


def clean_schema(schema: Any) -> Any:
    """Buang keyword JSON Schema yang ditolak Gemini (rekursif)."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


# ---------------------------------------------------------------- request
def _parts(msg: UnifiedMessage) -> list[dict[str, Any]]:
    if msg.content is None:
        return []
    if isinstance(msg.content, str):
        return [{"text": msg.content}] if msg.content else []
    parts: list[dict[str, Any]] = []
    for part in msg.content:
        if isinstance(part, TextPart):
            parts.append({"text": part.text})
        elif isinstance(part, ImagePart):
            img = parse_image_url(part.image_url.url)
            if img.data_b64 is not None:
                parts.append(
                    {"inline_data": {"mime_type": img.mime_type, "data": img.data_bytes()}}
                )
            else:
                parts.append({"file_data": {"mime_type": img.mime_type, "file_uri": img.url}})
    return parts


def _function_response(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"result": content}
    return value if isinstance(value, dict) else {"result": value}


def build_contents(messages: list[UnifiedMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts = [m.text() for m in messages if m.role in ("system", "developer")]
    call_names: dict[str, str] = {}
    contents: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role in ("system", "developer"):
            continue
        if msg.role == "tool":
            base_id, _ = split_call_id(msg.tool_call_id or "")
            name = call_names.get(base_id) or msg.name or "tool"
            fr: dict[str, Any] = {"name": name, "response": _function_response(msg.text())}
            if base_id and not base_id.startswith("call_"):
                fr["id"] = base_id  # id asli dari Gemini
            role, parts = "user", [{"function_response": fr}]
        else:
            role = "model" if msg.role == "assistant" else "user"
            parts = _parts(msg)
            for tc in msg.tool_calls or []:
                base_id, sig = split_call_id(tc.id)
                call_names[base_id] = tc.function.name
                fc: dict[str, Any] = {
                    "name": tc.function.name,
                    "args": loads_arguments(tc.function.arguments),
                }
                if base_id and not base_id.startswith("call_"):
                    fc["id"] = base_id
                part: dict[str, Any] = {"function_call": fc}
                if sig:
                    part["thought_signature"] = base64.b64decode(sig)
                parts.append(part)
        if not parts:
            continue
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    system = "\n\n".join(p for p in system_parts if p) or None
    return system, contents


def map_tool_config(tool_choice: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        mode = {"auto": "AUTO", "required": "ANY", "none": "NONE"}.get(tool_choice, "AUTO")
        return {"function_calling_config": {"mode": mode}}
    name = (tool_choice.get("function") or {}).get("name") or tool_choice.get("name")
    if name:
        return {"function_calling_config": {"mode": "ANY", "allowed_function_names": [name]}}
    return {"function_calling_config": {"mode": "AUTO"}}


def build_request(
    model: ModelConfig, req: UnifiedChatRequest
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Kembalikan (contents, config) untuk generate_content."""
    system, contents = build_contents(req.messages)
    config: dict[str, Any] = {
        "system_instruction": system,
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_output_tokens": req.max_tokens,
        "stop_sequences": req.stop,
        "seed": req.seed,
    }
    if req.tools:
        decls = []
        for t in req.tools:
            decl: dict[str, Any] = {"name": t.function.name}
            if t.function.description:
                decl["description"] = t.function.description
            if t.function.parameters:
                decl["parameters_json_schema"] = clean_schema(t.function.parameters)
            decls.append(decl)
        config["tools"] = [{"function_declarations": decls}]
        config["tool_config"] = map_tool_config(req.tool_choice)
    rf = req.response_format or {}
    if rf.get("type") in ("json_object", "json_schema"):
        config["response_mime_type"] = "application/json"
        schema = (rf.get("json_schema") or {}).get("schema")
        if schema:
            config["response_json_schema"] = clean_schema(schema)
    config = {k: v for k, v in config.items() if v is not None}
    config.update({k: v for k, v in req.provider_options.items() if k not in GATEWAY_ONLY_OPTIONS})
    return contents, config


# --------------------------------------------------------------- response
def parse_usage(meta: dict[str, Any] | None) -> Usage | None:
    if not meta:
        return None
    return Usage(
        prompt_tokens=meta.get("prompt_token_count") or 0,
        completion_tokens=(meta.get("candidates_token_count") or 0)
        + (meta.get("thoughts_token_count") or 0),
        cached_tokens=meta.get("cached_content_token_count") or 0,
    )


def _signature(part: dict[str, Any]) -> str | None:
    sig = part.get("thought_signature")
    if sig is None:
        return None
    if isinstance(sig, bytes):
        return base64.b64encode(sig).decode()
    return str(sig)  # model_dump(mode="json") → sudah base64


def _tool_call(part: dict[str, Any]) -> ToolCall:
    fc = part["function_call"]
    call_id = fc.get("id")
    sig = _signature(part)
    if call_id:
        call_id = f"{call_id}{_SIG_SEP}{sig}" if sig else call_id
    else:
        call_id = new_call_id(sig)
    return ToolCall(
        id=call_id,
        function=FunctionCall(name=fc.get("name") or "", arguments=dumps_arguments(fc.get("args"))),
    )


def map_finish(reason: str | None, has_tool_calls: bool) -> str | None:
    if has_tool_calls:
        return "tool_calls"
    if reason is None:
        return None
    return FINISH_MAP.get(reason, "stop")


def parse_response(
    data: dict[str, Any], *, include_reasoning: bool = False, upstream_model: str = ""
) -> UnifiedChatResponse:
    candidate = (data.get("candidates") or [{}])[0]
    texts: list[str] = []
    thoughts: list[str] = []
    tool_calls: list[ToolCall] = []
    for part in (candidate.get("content") or {}).get("parts") or []:
        if part.get("function_call"):
            tool_calls.append(_tool_call(part))
        elif part.get("text") is not None:
            (thoughts if part.get("thought") else texts).append(part["text"])
    return UnifiedChatResponse(
        content="".join(texts) if texts else None,
        tool_calls=tool_calls or None,
        finish_reason=map_finish(candidate.get("finish_reason"), bool(tool_calls)),
        usage=parse_usage(data.get("usage_metadata")) or Usage(),
        upstream_model=data.get("model_version") or upstream_model,
        raw_id=data.get("response_id"),
        reasoning_content="".join(thoughts) if include_reasoning and thoughts else None,
    )


@dataclass
class StreamTranslator:
    """Respons parsial generate_content_stream → UnifiedChunk. function_call datang utuh →
    satu delta_tool_calls lengkap. Usage diambil dari chunk terakhir (finish())."""

    include_reasoning: bool = False
    usage: Usage | None = None
    finish_reason: str | None = None
    model: str | None = None
    _tool_count: int = 0
    _raw_finish: str | None = None
    _started: bool = field(default=False)

    @property
    def started(self) -> bool:
        return self._started

    def feed(self, data: dict[str, Any]) -> list[UnifiedChunk]:
        out: list[UnifiedChunk] = []
        self.model = data.get("model_version") or self.model
        usage = parse_usage(data.get("usage_metadata"))
        if usage is not None:
            self.usage = usage
        for candidate in (data.get("candidates") or [])[:1]:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("function_call"):
                    tc = _tool_call(part)
                    out.append(
                        UnifiedChunk(
                            delta_tool_calls=[
                                ToolCallDelta(
                                    index=self._tool_count,
                                    id=tc.id,
                                    name=tc.function.name,
                                    arguments=tc.function.arguments,
                                )
                            ]
                        )
                    )
                    self._tool_count += 1
                elif part.get("text"):
                    if part.get("thought"):
                        if self.include_reasoning:
                            out.append(UnifiedChunk(delta_reasoning=part["text"]))
                    else:
                        out.append(UnifiedChunk(delta_content=part["text"]))
            if candidate.get("finish_reason"):
                self._raw_finish = candidate["finish_reason"]
        if out:
            self._started = True
        return out

    def finish(self) -> UnifiedChunk:
        reason = map_finish(self._raw_finish, self._tool_count > 0) or "stop"
        return UnifiedChunk(
            finish_reason=reason,
            usage=self.usage or Usage(estimated=True),
            upstream_model=self.model,
        )
