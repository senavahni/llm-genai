"""Biaya & usage AKTUAL langsung dari provider (bukan estimasi Gateway).

- OpenAI: Costs API `/v1/organization/costs` + Usage API `/v1/organization/usage/completions`
  (admin key `sk-admin-...`, waktu Unix detik, `amount.value` dalam USD).
- Anthropic: `/v1/organizations/cost_report` + `/v1/organizations/usage_report/messages`
  (admin key `sk-ant-admin01-...`, waktu RFC 3339, `amount` = string desimal dalam SEN).

Data provider bersifat per organisasi (termasuk pemakaian di luar Gateway), harian (UTC), dan
muncul beberapa menit setelah request. Hasil di-cache singkat agar konsol tidak membebani API.
"""

import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any

import httpx2

from app.utils.logger import get_logger

log = get_logger(__name__)

OPENAI_BASE = "https://api.openai.com/v1/organization"
ANTHROPIC_BASE = "https://api.anthropic.com/v1/organizations"
ANTHROPIC_VERSION = "2023-06-01"
MAX_BUCKETS_PER_PAGE = 31
MAX_PAGES = 24  # batas aman paginasi (± 2 tahun data harian)
REQUEST_TIMEOUT_S = 20.0
CACHE_TTL_S = 300.0
CENTS = Decimal(100)

_cache: dict[tuple[str, date, date], tuple[float, dict[str, Any]]] = {}


class BillingError(Exception):
    """Respons provider bukan 2xx / tidak bisa dibaca (pesan aman ditampilkan)."""


def _range(start: date, end: date) -> tuple[datetime, datetime]:
    """`end` inklusif (tanggal) → batas akhir eksklusif 00:00 UTC hari berikutnya."""
    return (
        datetime.combine(start, dtime(), tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), dtime(), tzinfo=UTC),
    )


async def _get_pages(
    http: httpx2.AsyncClient, url: str, params: dict[str, Any], headers: dict[str, str]
) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    page: str | None = None
    for _ in range(MAX_PAGES):
        query = {**params, **({"page": page} if page else {})}
        try:
            resp = await http.get(url, params=query, headers=headers, timeout=REQUEST_TIMEOUT_S)
        except httpx2.HTTPError as exc:
            raise BillingError(f"tidak bisa menghubungi provider: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise BillingError(f"HTTP {resp.status_code}: {_error_message(resp)}")
        body = resp.json()
        buckets.extend(body.get("data") or [])
        page = body.get("next_page")
        if not page:
            return buckets
    log.warning("provider_billing.max_pages", extra={"url": url})
    return buckets


def _error_message(resp: httpx2.Response) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        return resp.reason_phrase or "error"
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or "error")[:300]
    return str(err or resp.reason_phrase or "error")[:300]


def _result(
    provider: str,
    *,
    cost_by_day: dict[str, Decimal],
    tokens: dict[str, int],
    requests: int | None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": True,
        "ok": True,
        "error": None,
        "cost_usd": str(sum(cost_by_day.values(), Decimal(0))),
        "by_day": [{"day": d, "cost_usd": str(v)} for d, v in sorted(cost_by_day.items())],
        "tokens": tokens,
        "requests": requests,
    }


def _failed(provider: str, *, configured: bool, error: str | None) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": configured,
        "ok": False,
        "error": error,
        "cost_usd": None,
        "by_day": [],
        "tokens": None,
        "requests": None,
    }


async def fetch_openai(
    http: httpx2.AsyncClient, admin_key: str, start: date, end: date
) -> dict[str, Any]:
    since, until = _range(start, end)
    params = {
        "start_time": int(since.timestamp()),
        "end_time": int(until.timestamp()),
        "bucket_width": "1d",
        "limit": MAX_BUCKETS_PER_PAGE,
    }
    headers = {"Authorization": f"Bearer {admin_key}"}
    try:
        costs = await _get_pages(http, f"{OPENAI_BASE}/costs", params, headers)
        usage = await _get_pages(http, f"{OPENAI_BASE}/usage/completions", params, headers)
    except BillingError as exc:
        return _failed("openai", configured=True, error=str(exc))

    cost_by_day: dict[str, Decimal] = defaultdict(Decimal)
    for bucket in costs:
        day = datetime.fromtimestamp(bucket["start_time"], UTC).date().isoformat()
        for r in bucket.get("results") or []:
            cost_by_day[day] += Decimal(str((r.get("amount") or {}).get("value") or 0))
    tokens = {"input": 0, "output": 0, "cached": 0}
    requests = 0
    for bucket in usage:
        for r in bucket.get("results") or []:
            tokens["input"] += int(r.get("input_tokens") or 0)
            tokens["output"] += int(r.get("output_tokens") or 0)
            tokens["cached"] += int(r.get("input_cached_tokens") or 0)
            requests += int(r.get("num_model_requests") or 0)
    return _result("openai", cost_by_day=cost_by_day, tokens=tokens, requests=requests)


async def fetch_anthropic(
    http: httpx2.AsyncClient, admin_key: str, start: date, end: date
) -> dict[str, Any]:
    since, until = _range(start, end)
    params = {
        "starting_at": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1d",
        "limit": MAX_BUCKETS_PER_PAGE,
    }
    headers = {"x-api-key": admin_key, "anthropic-version": ANTHROPIC_VERSION}
    try:
        costs = await _get_pages(http, f"{ANTHROPIC_BASE}/cost_report", params, headers)
        usage = await _get_pages(http, f"{ANTHROPIC_BASE}/usage_report/messages", params, headers)
    except BillingError as exc:
        return _failed("anthropic", configured=True, error=str(exc))

    cost_by_day: dict[str, Decimal] = defaultdict(Decimal)
    for bucket in costs:
        day = bucket["starting_at"][:10]
        for r in bucket.get("results") or []:
            cost_by_day[day] += Decimal(str(r.get("amount") or 0)) / CENTS
    tokens = {"input": 0, "output": 0, "cached": 0}
    for bucket in usage:
        for r in bucket.get("results") or []:
            creation = r.get("cache_creation") or {}
            tokens["input"] += (
                int(r.get("uncached_input_tokens") or 0)
                + int(creation.get("ephemeral_5m_input_tokens") or 0)
                + int(creation.get("ephemeral_1h_input_tokens") or 0)
            )
            tokens["output"] += int(r.get("output_tokens") or 0)
            tokens["cached"] += int(r.get("cache_read_input_tokens") or 0)
    return _result("anthropic", cost_by_day=cost_by_day, tokens=tokens, requests=None)


FETCHERS = {"openai": fetch_openai, "anthropic": fetch_anthropic}


async def provider_billing(
    http: httpx2.AsyncClient, admin_keys: dict[str, str | None], start: date, end: date
) -> list[dict[str, Any]]:
    """Satu entri per provider; admin key kosong → `configured: false` tanpa panggilan HTTP."""
    out = []
    for provider, fetch in FETCHERS.items():
        key = admin_keys.get(provider)
        if not key:
            out.append(_failed(provider, configured=False, error=None))
            continue
        cached = _cache.get((provider, start, end))
        if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
            out.append(cached[1])
            continue
        result = await fetch(http, key, start, end)
        if result["ok"]:
            _cache[(provider, start, end)] = (time.monotonic(), result)
        out.append(result)
    return out
