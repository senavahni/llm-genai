from datetime import date
from decimal import Decimal

import httpx2

from app.services import provider_billing as pb
from tests.unit.providers.conftest import json_response

START, END = date(2026, 11, 1), date(2026, 11, 2)


def _bucket(start: int, results: list[dict]) -> dict:
    return {"object": "bucket", "start_time": start, "end_time": start + 86400, "results": results}


async def test_openai_sums_costs_across_pages_and_usage_tokens(mock_http):
    nov1, nov2 = 1_793_491_200, 1_793_577_600  # 2026-11-01 / 02 00:00 UTC

    def handler(req: httpx2.Request) -> httpx2.Response:
        if req.url.path.endswith("/organization/costs"):
            if req.url.params.get("page") == "p2":
                cost = [_bucket(nov2, [{"amount": {"value": 0.25, "currency": "usd"}}])]
                return json_response({"data": cost, "has_more": False, "next_page": None})
            cost = [_bucket(nov1, [{"amount": {"value": 1.5, "currency": "usd"}}])]
            return json_response({"data": cost, "has_more": True, "next_page": "p2"})
        usage = [
            _bucket(
                nov1,
                [
                    {
                        "input_tokens": 1000,
                        "output_tokens": 200,
                        "input_cached_tokens": 300,
                        "num_model_requests": 4,
                    }
                ],
            )
        ]
        return json_response({"data": usage, "has_more": False, "next_page": None})

    http, rec = mock_http(handler)
    out = await pb.fetch_openai(http, "sk-admin-test", START, END)

    assert out["ok"] and out["error"] is None
    assert Decimal(out["cost_usd"]) == Decimal("1.75")
    assert out["by_day"] == [
        {"day": "2026-11-01", "cost_usd": "1.5"},
        {"day": "2026-11-02", "cost_usd": "0.25"},
    ]
    assert out["tokens"] == {"input": 1000, "output": 200, "cached": 300}
    assert out["requests"] == 4
    first = rec.requests[0]
    assert first.headers["authorization"] == "Bearer sk-admin-test"
    assert first.url.params["start_time"] == str(nov1)
    assert first.url.params["end_time"] == str(nov2 + 86400)  # akhir eksklusif = hari setelah END


async def test_anthropic_converts_cents_and_counts_cache_tokens(mock_http):
    def handler(req: httpx2.Request) -> httpx2.Response:
        if req.url.path.endswith("/cost_report"):
            results = [{"amount": "123.45", "currency": "USD"}, {"amount": "10", "currency": "USD"}]
            data = [
                {
                    "starting_at": "2026-11-01T00:00:00Z",
                    "ending_at": "2026-11-02T00:00:00Z",
                    "results": results,
                }
            ]
            return json_response({"data": data, "has_more": False, "next_page": None})
        usage = {
            "uncached_input_tokens": 500,
            "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 50},
            "cache_read_input_tokens": 400,
            "output_tokens": 70,
        }
        data = [
            {
                "starting_at": "2026-11-01T00:00:00Z",
                "ending_at": "2026-11-02T00:00:00Z",
                "results": [usage],
            }
        ]
        return json_response({"data": data, "has_more": False, "next_page": None})

    http, rec = mock_http(handler)
    out = await pb.fetch_anthropic(http, "sk-ant-admin01-test", START, END)

    assert Decimal(out["cost_usd"]) == Decimal("1.3345")  # (123.45 + 10) sen
    assert out["by_day"] == [{"day": "2026-11-01", "cost_usd": "1.3345"}]
    assert out["tokens"] == {"input": 650, "output": 70, "cached": 400}
    assert out["requests"] is None  # usage report Anthropic tidak memuat jumlah request
    first = rec.requests[0]
    assert first.headers["x-api-key"] == "sk-ant-admin01-test"
    assert first.headers["anthropic-version"]
    assert first.url.params["starting_at"] == "2026-11-01T00:00:00Z"
    assert first.url.params["ending_at"] == "2026-11-03T00:00:00Z"


async def test_http_error_is_reported_without_raising(mock_http):
    http, _ = mock_http(
        lambda r: json_response({"error": {"message": "invalid admin key"}}, status=401)
    )
    out = await pb.fetch_openai(http, "sk-admin-bad", START, END)
    assert out["ok"] is False
    assert "401" in out["error"] and "invalid admin key" in out["error"]
    assert "sk-admin-bad" not in out["error"]


async def test_unconfigured_providers_make_no_calls(mock_http):
    http, rec = mock_http(lambda r: json_response({}))
    out = await pb.provider_billing(http, {"openai": None, "anthropic": None}, START, END)
    assert [p["provider"] for p in out] == ["openai", "anthropic"]
    assert all(p["configured"] is False and p["ok"] is False for p in out)
    assert rec.requests == []
