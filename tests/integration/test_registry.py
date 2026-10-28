import logging

import pytest
from sqlalchemy import update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.registry import ProviderRegistry
from app.models import Model, Provider
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.local_runtime_provider import LocalRuntimeProvider
from app.utils.errors import ModelNotFound
from tests.integration.test_db_models import _load_manage, _seed_data

pytestmark = pytest.mark.integration


async def _seed():
    manage = _load_manage()
    async with SessionLocal() as s:
        await manage._seed(s, _seed_data(), update_local=False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123456")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")


async def test_load_providers_models_routes(db, keys, caplog):
    await _seed()
    registry = ProviderRegistry(get_settings())
    with caplog.at_level(logging.WARNING):
        await registry.load()
    try:
        assert isinstance(registry.get("anthropic"), AnthropicProvider)
        assert isinstance(registry.get("openvino"), LocalRuntimeProvider)
        # provider remote tanpa API key ter-skip dengan WARNING, tidak crash
        assert registry.get("openai") is None and registry.get("gemini") is None
        assert "OPENAI_API_KEY" in registry.disabled["openai"]
        assert "provider_disabled" in caplog.text

        cat = registry.catalog
        coder = cat.get_model("local/qwen2.5-coder-1.5b")
        assert coder.device == "npu" and coder.is_pinned and coder.supports_fim
        assert coder.runtime_backend == "openvino_llm" and coder.vram_mb > 0
        assert cat.get_model("local/sd-1.5").provider_code == "openvino"
        smart = cat.get_route("smart")
        assert [t.model_alias for t in smart.targets] == [
            "anthropic/claude-sonnet",
            "openai/gpt-heavy",
            "local/qwen2.5-7b",
        ]
        with pytest.raises(ModelNotFound):
            cat.get_model("nope")
    finally:
        await registry.close()


async def test_reload_reflects_db_changes_without_restart(db, keys):
    await _seed()
    registry = ProviderRegistry(get_settings())
    await registry.load()
    try:
        anthropic_before = registry.get("anthropic")
        async with SessionLocal() as s:
            await s.execute(
                update(Model)
                .where(Model.alias == "local/qwen2.5-7b")
                .values(vram_mb=4321, is_pinned=True)
            )
            await s.execute(
                update(Provider).where(Provider.code == "openvino").values(is_enabled=False)
            )
            await s.commit()
        await registry.reload()
        model = registry.catalog.get_model("local/qwen2.5-7b")
        assert model.vram_mb == 4321 and model.is_pinned
        assert registry.get("openvino") is None and registry.disabled["openvino"]
        assert registry.get("anthropic") is anthropic_before  # konfigurasi sama → dipakai ulang
    finally:
        await registry.close()
