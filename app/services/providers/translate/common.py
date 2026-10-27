import base64
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_to_bytes

_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?P<b64>;base64)?,(?P<data>.*)$", re.S)


@dataclass(frozen=True, slots=True)
class ParsedImage:
    mime_type: str
    data_b64: str | None = None  # isi bila data URL
    url: str | None = None  # isi bila http(s) URL

    def data_bytes(self) -> bytes:
        assert self.data_b64 is not None
        return base64.b64decode(self.data_b64)


def parse_image_url(url: str) -> ParsedImage:
    match = _DATA_URL.match(url)
    if match:
        mime = match.group("mime") or "image/png"
        data = match.group("data")
        if not match.group("b64"):
            data = base64.b64encode(unquote_to_bytes(data)).decode()
        return ParsedImage(mime_type=mime, data_b64=data)
    lowered = url.lower().split("?")[0]
    mime = "image/png"
    for ext, m in (
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
    ):
        if lowered.endswith(ext):
            mime = m
    return ParsedImage(mime_type=mime, url=url)


def loads_arguments(arguments: str | None) -> dict[str, Any]:
    """Argumen tool call (string JSON OpenAI) → dict. JSON rusak dibungkus agar tidak hilang."""
    if not arguments:
        return {}
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return {"_raw_arguments": arguments}
    return value if isinstance(value, dict) else {"value": value}


def dumps_arguments(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))
