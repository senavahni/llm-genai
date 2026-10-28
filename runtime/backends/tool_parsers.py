"""Parser tool call dari teks keluaran model → format OpenAI `tool_calls`.

Semua model chat lokal adalah Qwen2.5 (template Hermes): definisi tools disisipkan template chat
native (`Tokenizer.apply_chat_template(..., tools=...)`) dan model menjawab dengan
`<tool_call>{"name": ..., "arguments": {...}}</tool_call>` (bisa berulang)."""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"
_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


@dataclass(frozen=True, slots=True)
class ParsedOutput:
    content: str | None  # teks di luar blok tool call (None bila kosong)
    tool_calls: list[dict[str, Any]]


def _to_openai(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str) or not obj["name"]:
        return None
    args = obj.get("arguments", obj.get("parameters", {}))
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": obj["name"],
            # OpenAI: arguments = string JSON
            "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
        },
    }


def parse_hermes(text: str) -> ParsedOutput:
    """Blok yang JSON-nya rusak dibiarkan sebagai teks biasa (tidak dibuang diam-diam)."""
    calls: list[dict[str, Any]] = []
    kept: list[str] = []
    last = 0
    for match in _BLOCK.finditer(text):
        try:
            call = _to_openai(json.loads(match.group(1)))
        except json.JSONDecodeError:
            call = None
        kept.append(text[last : match.start()])
        if call is None:
            kept.append(match.group(0))
        else:
            calls.append(call)
        last = match.end()
    kept.append(text[last:])
    content = "".join(kept).strip()
    return ParsedOutput(content=content or None, tool_calls=calls)
