import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_SECRET_LEN = 32


class ConfigError(Exception):
    """Konfigurasi tidak valid; pesan sudah siap ditampilkan ke operator."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    log_dir: str = "./logs"
    enable_docs: bool = False  # paksa /docs aktif walau app_env != dev

    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 10

    gateway_key_pepper: SecretStr
    default_rpm_limit: int = 120
    default_tpm_limit: int = 200_000
    max_body_mb: int = 20
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    trust_proxy: bool = False
    storage_dir: str = "./storage"
    sse_heartbeat_s: float = 15.0  # komentar `: ping` saat stream diam; 0 = mati
    provider_health_timeout_s: float = 5.0

    # --- Local Runtime (dipakai gateway & runtime) ---
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 8100
    runtime_url: str = "http://127.0.0.1:8100/v1"
    runtime_token: SecretStr
    models_dir: str = "./local_models"
    ov_cache_dir: str = "./local_models/ov_cache"
    hf_home: str = "./local_models/hf_cache"
    gpu_total_mb: int = 8192
    gpu_reserve_mb: int = 1000
    npu_total_mb: int = 8192
    npu_reserve_mb: int = 700
    allow_cpu_fallback: bool = False
    runtime_queue_timeout_s: int = 30
    runtime_min_residency_s: int = 60
    local_first_token_timeout_s: int = 120

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("DATABASE_URL kosong")
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL harus memakai driver async: postgresql+asyncpg://...")
        if "CHANGE_ME" in v:
            raise ValueError("DATABASE_URL masih berisi placeholder CHANGE_ME")
        return v

    @field_validator("gateway_key_pepper", "runtime_token")
    @classmethod
    def _check_strong_secret(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if "CHANGE_ME" in raw:
            raise ValueError("masih berisi placeholder CHANGE_ME")
        if len(raw) < MIN_SECRET_LEN:
            raise ValueError(f"terlalu lemah: minimal {MIN_SECRET_LEN} karakter")
        return v

    @property
    def gpu_budget_mb(self) -> int:
        return self.gpu_total_mb - self.gpu_reserve_mb

    @property
    def npu_budget_mb(self) -> int:
        return self.npu_total_mb - self.npu_reserve_mb

    @property
    def max_body_bytes(self) -> int:
        return self.max_body_mb * 1024 * 1024

    @property
    def docs_enabled(self) -> bool:
        return self.app_env == "dev" or self.enable_docs

    def provider_secret(self, env_name: str | None) -> str | None:
        """Ambil nilai secret berdasarkan nama env yang tersimpan di tabel providers."""
        if not env_name:
            return None
        value = os.environ.get(env_name)
        if value:
            return value
        field = getattr(self, env_name.lower(), None)
        if isinstance(field, SecretStr):
            return field.get_secret_value() or None
        if isinstance(field, str):
            return field or None
        return None

    def startup_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.allow_cpu_fallback and self.app_env == "prod":
            warnings.append(
                "!!! ALLOW_CPU_FALLBACK=true di APP_ENV=prod: model lokal dapat berjalan di CPU "
                "(lambat, melanggar NF9). Matikan kecuali sedang debug. !!!"
            )
        return warnings


def load_settings(**overrides: object) -> Settings:
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]).upper() or "?"
            msg = "wajib diisi" if err["type"] == "missing" else err["msg"]
            lines.append(f"  - {field}: {msg}")
        raise ConfigError("Konfigurasi tidak valid (.env):\n" + "\n".join(lines)) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
