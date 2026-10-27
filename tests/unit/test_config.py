import pytest

from app.core.config import ConfigError, load_settings

GOOD = "z" * 40


def test_missing_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="DATABASE_URL: wajib diisi"):
        load_settings(_env_file=None)


@pytest.mark.parametrize("pepper", ["short", "CHANGE_ME_LONG_RANDOM" + "x" * 30])
def test_weak_pepper_rejected(pepper):
    with pytest.raises(ConfigError, match="GATEWAY_KEY_PEPPER"):
        load_settings(gateway_key_pepper=pepper)


def test_weak_runtime_token_rejected():
    with pytest.raises(ConfigError, match="RUNTIME_TOKEN"):
        load_settings(runtime_token="CHANGE_ME_RANDOM")


def test_database_url_must_be_async_and_not_placeholder():
    with pytest.raises(ConfigError, match="asyncpg"):
        load_settings(database_url="postgresql://u:p@h/db")
    with pytest.raises(ConfigError, match="CHANGE_ME"):
        load_settings(database_url="postgresql+asyncpg://u:CHANGE_ME@h/db")


def test_cors_origins_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert load_settings().cors_origins == ["http://a.test", "http://b.test"]
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert load_settings().cors_origins == []


def test_budgets_and_body_bytes():
    s = load_settings(gpu_total_mb=8192, gpu_reserve_mb=1000, npu_total_mb=8192, npu_reserve_mb=700)
    assert s.gpu_budget_mb == 7192  # PRD membulatkan menjadi "7200 MB / 7,2 GB"
    assert s.npu_budget_mb == 7492
    assert load_settings(max_body_mb=2).max_body_bytes == 2 * 1024 * 1024


def test_provider_secret(monkeypatch):
    monkeypatch.setenv("SOME_PROVIDER_KEY", "abc")
    s = load_settings(anthropic_api_key="sk-ant-from-settings")
    assert s.provider_secret("SOME_PROVIDER_KEY") == "abc"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert s.provider_secret("ANTHROPIC_API_KEY") == "sk-ant-from-settings"
    assert s.provider_secret("RUNTIME_TOKEN") == s.runtime_token.get_secret_value()
    assert s.provider_secret(None) is None
    assert s.provider_secret("DOES_NOT_EXIST") is None


def test_cpu_fallback_in_prod_warns():
    assert load_settings(app_env="prod", allow_cpu_fallback=True).startup_warnings()
    assert not load_settings(app_env="dev", allow_cpu_fallback=True).startup_warnings()
    assert not load_settings(app_env="prod", allow_cpu_fallback=False).startup_warnings()


def test_secrets_not_in_repr():
    s = load_settings(gateway_key_pepper=GOOD)
    assert GOOD not in repr(s)
