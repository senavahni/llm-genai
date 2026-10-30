"""Parser tool call dari teks keluaran model → format OpenAI `tool_calls`.

Semua model chat lokal adalah Qwen2.5 (template Hermes): definisi tools disisipkan template chat
native (`Tokenizer.apply_chat_template(..., tools=...)`) dan model menjawab dengan
`<tool_call>{"name": ..., "arguments": {...}}</tool_call>` (bisa berulang)."""

import json
import re
import uuid
from collections.abc import Iterable
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


def parse_tool_output(text: str, tool_names: Iterable[str]) -> ParsedOutput:
    """Hermes `<tool_call>` dulu; bila tidak ada, fallback format menyimpang yang ketat."""
    parsed = parse_hermes(text)
    if parsed.tool_calls:
        return parsed
    calls = parse_lenient(text, set(tool_names))
    return ParsedOutput(content=None, tool_calls=calls) if calls else parsed


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


_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z]*\s*")
_WRAPPER_TAGS = re.compile(r"</?(tools|tool_call|function_call)>")


def _unwrap(text: str) -> str:
    """Buang pagar kode & tag pembungkus yang kadang dipakai model alih-alih `<tool_call>`."""
    text = _FENCE_OPEN.sub("", text.strip())
    text = re.sub(r"```\s*$", "", text)
    return _WRAPPER_TAGS.sub("", text).strip()


def parse_lenient(text: str, tool_names: set[str]) -> list[dict[str, Any]]:
    """Fallback untuk model yang memanggil tool dengan format menyimpang (mis. Qwen2.5-Coder:
    ```` ```xml\\n<tools>{"name":…}</tools>``` ````). Hanya diterima bila SELURUH teks (setelah
    pagar/tag dibuang) adalah objek JSON berisi `name` yang termasuk tools caller; selain itu
    dianggap jawaban biasa (mencegah salah tafsir contoh JSON di jawaban)."""
    body = _unwrap(text)
    if not body or not tool_names:
        return []
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(body):
            break
        try:
            obj, pos = decoder.raw_decode(body, pos)
        except json.JSONDecodeError:
            return []
        objects.extend(obj if isinstance(obj, list) else [obj])
    calls = []
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("name") not in tool_names:
            return []
        call = _to_openai(obj)
        if call is None:
            return []
        calls.append(call)
    return calls


def _could_be_lenient_call(text: str) -> bool | None:
    """Awal output: True/None = mungkin tool call menyimpang (tahan), False = jelas bukan."""
    stripped = text.lstrip()
    if not stripped:
        return None
    if "```".startswith(stripped) or "<tools>".startswith(stripped):
        return None  # masih terlalu pendek untuk diputuskan
    if stripped.startswith("```"):
        head, sep, rest = stripped[3:].partition("\n")
        if not sep:
            return None if head.isalpha() or not head else False
        if head.strip().lower() not in ("", "json", "xml"):
            return False  # mis. ```python → jawaban kode biasa
        stripped = rest.lstrip()
        if not stripped:
            return None
    for tag in ("<tools>", "<function_call>"):
        if stripped.startswith(tag):
            stripped = stripped[len(tag) :].lstrip()
        elif tag.startswith(stripped):
            return None
    if not stripped:
        return None
    return stripped[0] in "{["


class StreamToolParser:
    """Parser inkremental untuk stream: teks di luar `<tool_call>…</tool_call>` diteruskan
    segera sebagai `("content", teks)`; isi blok di-buffer sampai penutup lalu dikirim sebagai
    `("tool_call", call_openai)`. Potongan yang mungkin awal penanda (mis. `"<tool"`) ditahan
    sampai jelas. Blok rusak/terpotong dikembalikan sebagai teks biasa.

    Bila `tool_names` diberikan, awal output yang mungkin tool call berformat menyimpang
    (lihat `parse_lenient`) ditahan sampai akhir stream lalu diputuskan."""

    def __init__(self, tool_names: set[str] | None = None) -> None:
        self._buf = ""
        self._in_block = False
        self._tool_names = tool_names or set()
        self._lenient: bool | None = None if tool_names else False  # None = belum diputuskan

    def feed(self, text: str) -> list[tuple[str, Any]]:
        if self._lenient is not False:
            self._buf += text
            decision = _could_be_lenient_call(self._buf)
            if decision is not False:
                self._lenient = decision
                if TOOL_CALL_OPEN not in self._buf:
                    return []  # tahan: mungkin seluruh output adalah tool call
            self._lenient = False
            text, self._buf = self._buf, ""
        self._buf += text
        events: list[tuple[str, Any]] = []
        while True:
            if not self._in_block:
                idx = self._buf.find(TOOL_CALL_OPEN)
                if idx >= 0:
                    if idx:
                        events.append(("content", self._buf[:idx]))
                    self._buf = self._buf[idx:]
                    self._in_block = True
                    continue
                keep = _partial_suffix(self._buf, TOOL_CALL_OPEN)
                emit = self._buf[: len(self._buf) - keep]
                if emit:
                    events.append(("content", emit))
                self._buf = self._buf[len(emit) :]
                return events
            end = self._buf.find(TOOL_CALL_CLOSE)
            if end < 0:
                return events
            block = self._buf[: end + len(TOOL_CALL_CLOSE)]
            self._buf = self._buf[end + len(TOOL_CALL_CLOSE) :]
            self._in_block = False
            parsed = parse_hermes(block)
            if parsed.tool_calls:
                events.extend(("tool_call", call) for call in parsed.tool_calls)
            else:
                events.append(("content", block))

    def finish(self) -> list[tuple[str, Any]]:
        """Akhir stream: buffer yang ditahan diputuskan (tool call menyimpang atau teks); sisa
        lain (termasuk blok tanpa penutup) dikirim sebagai teks."""
        rest, in_block = self._buf, self._in_block
        self._buf, self._in_block = "", False
        # blok `<tool_call>` tanpa penutup (model berhenti sebelum `</tool_call>`, sering pada
        # Qwen2-VL): diperlakukan sama dengan non-stream (parse_tool_output → parse_lenient)
        if (self._lenient is not False or in_block) and rest:
            calls = parse_lenient(rest, self._tool_names)
            if calls:
                return [("tool_call", call) for call in calls]
        return [("content", rest)] if rest else []


def _partial_suffix(text: str, marker: str) -> int:
    """Panjang akhiran `text` yang merupakan awalan `marker` (calon penanda terpotong)."""
    for n in range(min(len(marker) - 1, len(text)), 0, -1):
        if marker.startswith(text[-n:]):
            return n
    return 0
