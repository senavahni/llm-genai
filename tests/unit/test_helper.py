from datetime import UTC
from decimal import Decimal

from app.utils.helper import (
    calc_cost,
    client_ip,
    estimate_tokens,
    glob_match,
    new_request_id,
    utcnow,
)


def test_new_request_id_is_uuid7_and_ordered():
    ids = [new_request_id() for _ in range(50)]
    assert all(i.version == 7 for i in ids)
    assert all(i.variant == "specified in RFC 4122" for i in ids)
    assert len(set(ids)) == 50
    # urut berdasarkan timestamp ms (48 bit pertama)
    stamps = [i.int >> 80 for i in ids]
    assert stamps == sorted(stamps)


def test_utcnow_is_aware():
    assert utcnow().tzinfo is UTC


def test_calc_cost():
    assert calc_cost(1_000_000, 0, Decimal("3"), Decimal("15")) == Decimal("3.00000000")
    assert calc_cost(1234, 567, "3", "15") == Decimal("0.01220700")
    assert calc_cost(1, 0, "0.15", 0) == Decimal("0.00000015")
    assert calc_cost(1, 0, "0.000005", 0) == Decimal("0.00000000")  # dibulatkan 8 digit
    assert calc_cost(1, 1, 0.000001, 0) == Decimal("0.00000000")
    assert calc_cost(0, 0, 0, 0) == Decimal("0E-8")
    assert isinstance(calc_cost(10, 10, 1.5, 2.5), Decimal)


def test_glob_match():
    assert glob_match("local/*", "local/qwen2.5-7b")
    assert glob_match("*", "anything")
    assert not glob_match("local/*", "openai/gpt")
    assert not glob_match("LOCAL/*", "local/x")  # case-sensitive


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    messages = [
        {"role": "system", "content": "a" * 8},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "b" * 4},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "abcd", "arguments": "{}"}}],
        },
    ]
    assert estimate_tokens(messages) == 5  # 8 + 4 + 4 + 2 = 18 char → ceil(18/4)


def _scope(client=("10.0.0.5", 1234), headers=()):
    return {"client": client, "headers": [(k.encode(), v.encode()) for k, v in headers]}


def test_client_ip():
    scope = _scope(headers=[("x-forwarded-for", "1.2.3.4, 10.0.0.1"), ("x-real-ip", "5.6.7.8")])
    assert client_ip(scope, trust_proxy=False) == "10.0.0.5"
    assert client_ip(scope, trust_proxy=True) == "1.2.3.4"
    assert client_ip(_scope(headers=[("x-real-ip", "5.6.7.8")]), trust_proxy=True) == "5.6.7.8"
    assert client_ip(_scope(client=None), trust_proxy=False) == "unknown"
