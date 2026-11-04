"""Admin Console: hanya dari localhost, header keamanan ketat, status .env tanpa nilai secret."""

import json

import httpx
import pytest

from app.core.config import load_settings
from app.main import create_app
from app.services.env_status import env_vars, provider_key_states, secret_state

SENTINEL = "sk-test-SENTINEL-must-never-leak-0123456789"


def _client(peer: str = "127.0.0.1", host: str = "127.0.0.1:8000") -> httpx.AsyncClient:
    app = create_app(load_settings())
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 50000)), base_url=f"http://{host}"
    )


async def test_console_served_to_localhost_with_strict_headers() -> None:
    async with _client() as c:
        r = await c.get("/console")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("host", ["localhost:8000", "[::1]:8000", "127.0.0.1"])
async def test_console_accepts_local_host_names(host: str) -> None:
    async with _client(host=host) as c:
        assert (await c.get("/console/kit.js")).status_code == 200


async def test_console_rejects_remote_peer() -> None:
    async with _client(peer="192.168.1.20") as c:
        r = await c.get("/console")
    assert r.status_code == 403


async def test_console_rejects_foreign_host_header() -> None:
    # DNS rebinding: peer loopback tetapi Host milik domain lain
    async with _client(host="evil.example:8000") as c:
        assert (await c.get("/console")).status_code == 403


@pytest.mark.parametrize("name", ["index.html", ".env", "..%2F.env", "x.py"])
async def test_console_serves_only_whitelisted_assets(name: str) -> None:
    async with _client() as c:
        assert (await c.get(f"/console/{name}")).status_code == 404


def test_secret_state_classifies_values() -> None:
    assert secret_state(None) == "missing"
    assert secret_state("") == "missing"
    assert secret_state("lgw_CHANGE_ME") == "placeholder"
    assert secret_state("short", min_len=32) == "weak"
    assert secret_state("x" * 40, min_len=32) == "ok"


def test_env_vars_never_expose_secret_values() -> None:
    settings = load_settings(openai_api_key=SENTINEL)
    rows = env_vars(settings)
    dumped = json.dumps(rows)
    assert SENTINEL not in dumped
    assert settings.gateway_key_pepper.get_secret_value() not in dumped
    assert settings.runtime_token.get_secret_value() not in dumped
    openai_row = next(r for r in rows if r["name"] == "OPENAI_API_KEY")
    assert openai_row == {**openai_row, "secret": True, "value": None, "state": "ok"}


def test_provider_key_states() -> None:
    settings = load_settings(openai_api_key=SENTINEL, anthropic_api_key=None)
    providers = [
        {
            "code": "openai",
            "display_name": "OpenAI",
            "is_enabled": True,
            "api_key_env": "OPENAI_API_KEY",
            "config": {},
        },
        {
            "code": "anthropic",
            "display_name": "Anthropic",
            "is_enabled": True,
            "api_key_env": "ANTHROPIC_API_KEY",
            "config": {},
        },
        {
            "code": "openvino",
            "display_name": "Lokal",
            "is_enabled": True,
            "api_key_env": None,
            "config": {},
        },
        {
            "code": "ollama",
            "display_name": "Ollama",
            "is_enabled": True,
            "api_key_env": "OLLAMA_API_KEY",
            "config": {"auth": "none"},
        },
    ]
    states = {p["code"]: p["key_state"] for p in provider_key_states(settings, providers)}
    assert states == {
        "openai": "ok",
        "anthropic": "missing",
        "openvino": "not_needed",
        "ollama": "not_needed",
    }
    assert SENTINEL not in json.dumps(provider_key_states(settings, providers))
