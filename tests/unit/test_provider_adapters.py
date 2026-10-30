"""Registry memilih adapter per provider (custom) dan tidak pernah memberi secret internal."""

import uuid

import httpx2
import pytest

from app.core import config as config_module
from app.core.config import get_settings, valid_provider_key_env
from app.core.registry import ProviderRegistry
from app.schemas.catalog import ProviderConfig
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.openai_provider import OpenAIProvider


def _cfg(code: str, *, env: str | None = None, **config) -> ProviderConfig:
    return ProviderConfig(
        id=uuid.uuid4(),
        code=code,
        kind="remote",
        display_name=code,
        base_url="https://api.example.com/v1",
        api_key_env=env,
        config=config,
    )


def _registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings(), http=httpx2.AsyncClient())


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("DEEPSEEK_API_KEY", True),
        ("OPENROUTER_API_KEY", True),
        ("GATEWAY_KEY_PEPPER", False),
        ("RUNTIME_TOKEN", False),
        ("DATABASE_URL", False),
        ("deepseek_api_key", False),
        (None, False),
    ],
)
def test_key_env_pattern(name, ok):
    assert valid_provider_key_env(name) is ok


def test_adapter_chosen_per_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("CLAUDE_PROXY_API_KEY", "k2")
    reg = _registry()
    assert reg._class_for(_cfg("groq", env="GROQ_API_KEY", adapter="openai")) is OpenAIProvider
    proxy = _cfg("claude-proxy", env="CLAUDE_PROXY_API_KEY", adapter="anthropic")
    assert reg._class_for(proxy) is AnthropicProvider
    assert reg._disabled_reason(proxy) is None
    assert "tidak dikenal" in reg._disabled_reason(_cfg("x", env="X_API_KEY", adapter="cohere"))
    # tanpa key: perlu auth=none eksplisit
    assert reg._disabled_reason(_cfg("ollama", adapter="openai", auth="none")) is None
    assert "tidak valid" in reg._disabled_reason(_cfg("ollama", adapter="openai"))


def test_internal_secret_never_used_as_provider_key():
    reg = _registry()
    evil = _cfg("evil", env="GATEWAY_KEY_PEPPER", adapter="openai")
    assert "tidak valid" in reg._disabled_reason(evil)
    provider = OpenAIProvider(evil, reg.http, get_settings())
    assert provider.api_key is None  # walau provider dibuat langsung


def test_custom_key_read_from_dotenv_and_static_headers(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(config_module, "_dotenv", lambda: {"MISTRAL_API_KEY": "dari-dotenv"})
    cfg = _cfg("mistral", env="MISTRAL_API_KEY", adapter="openai", headers={"X-Title": "gw"})
    provider = OpenAIProvider(cfg, httpx2.AsyncClient(), get_settings())
    assert provider.api_key == "dari-dotenv"
    assert provider.default_headers() == {"X-Title": "gw"}
