import fnmatch
import math
import os
import time
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_COST_QUANT = Decimal("0.00000001")  # 8 digit, sesuai NUMERIC(14,8)
_MTOK = Decimal(1_000_000)


def new_request_id() -> uuid.UUID:
    """UUIDv7 (RFC 9562): urut waktu sehingga ramah index B-tree/BRIN."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bit)
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)  # rand_b (62 bit)
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def calc_cost(
    prompt_tokens: int,
    completion_tokens: int,
    in_per_mtok: Decimal | float | str,
    out_per_mtok: Decimal | float | str,
) -> Decimal:
    cost = (
        Decimal(prompt_tokens) * _dec(in_per_mtok) + Decimal(completion_tokens) * _dec(out_per_mtok)
    ) / _MTOK
    return cost.quantize(_COST_QUANT, rounding=ROUND_HALF_UP)


def glob_match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern)


def _text_len(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, Mapping):
        # message {"role", "content"} atau content part {"type": "text", "text": ...}
        total = _text_len(content.get("content")) + _text_len(content.get("text"))
        for call in content.get("tool_calls") or []:
            fn = call.get("function") or {}
            total += _text_len(fn.get("name")) + _text_len(fn.get("arguments"))
        return total
    if isinstance(content, Iterable):
        return sum(_text_len(c) for c in content)
    return 0


def estimate_tokens(text_or_messages: Any) -> int:
    """Heuristik kasar len(chars)/4, hanya dipakai bila provider tidak memberi usage."""
    chars = _text_len(text_or_messages)
    return math.ceil(chars / 4) if chars else 0


def _header(scope: Mapping[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def client_ip(scope: Mapping[str, Any], trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = _header(scope, b"x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = _header(scope, b"x-real-ip")
        if real_ip:
            return real_ip.strip()
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"
