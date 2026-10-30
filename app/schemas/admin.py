"""Schema Admin API (TASK-17). `*Out` = snapshot aman (tanpa secret/hash) yang juga dipakai untuk
before/after audit log. `*Update` semua field opsional (PATCH: hanya field yang dikirim)."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------- project
class ProjectCreate(_In):
    slug: str
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    owner: str | None = Field(default=None, max_length=128)
    log_payloads: bool = False
    payload_retention_days: int = Field(default=7, ge=0, le=365)
    image_retention_days: int = Field(default=7, ge=1, le=365)
    default_model: str | None = None
    allowed_models: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("slug harus cocok ^[a-z0-9][a-z0-9-]{1,62}$")
        return v


class ProjectUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    owner: str | None = None
    status: Literal["active", "suspended"] | None = None
    log_payloads: bool | None = None
    payload_retention_days: int | None = Field(default=None, ge=0, le=365)
    image_retention_days: int | None = Field(default=None, ge=1, le=365)
    default_model: str | None = None


class ProjectOut(_Out):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    owner: str | None
    status: str
    log_payloads: bool
    payload_retention_days: int
    image_retention_days: int
    default_model: str | None
    created_at: datetime
    updated_at: datetime


class AllowedModelsSet(_In):
    patterns: list[str] = Field(min_length=1)

    @field_validator("patterns")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        cleaned = [p.strip() for p in v]
        if any(not p or len(p) > 128 for p in cleaned):
            raise ValueError("pola tidak boleh kosong dan maks 128 karakter")
        return list(dict.fromkeys(cleaned))


# --------------------------------------------------------------------- key
class KeyCreate(_In):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] | None = None
    rpm_limit: int | None = Field(default=None, ge=1)
    tpm_limit: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


class KeyRevoke(_In):
    reason: str = Field(min_length=1, max_length=500)


class ApiKeyOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    role: str
    key_prefix: str
    scopes: list[str]
    rpm_limit: int | None
    tpm_limit: int | None
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # ditampilkan sekali; tidak disimpan


# ---------------------------------------------------------------- provider
class ProviderUpdate(_In):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    is_enabled: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    max_concurrency: int | None = Field(default=None, ge=1, le=1000)
    base_url: str | None = Field(default=None, pattern=r"^https?://")
    # NAMA env berpola *_API_KEY (nilai di .env, tidak pernah di DB)
    api_key_env: str | None = Field(default=None, max_length=64)
    config: dict[str, Any] | None = None


class ProviderCreate(_In):
    """Provider remote baru dengan adapter yang sudah ada (format API kompatibel)."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    display_name: str = Field(min_length=1, max_length=64)
    adapter: Literal["openai", "anthropic", "gemini"] = "openai"
    base_url: str | None = Field(default=None, pattern=r"^https?://")
    api_key_env: str | None = Field(default=None, max_length=64)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_concurrency: int = Field(default=16, ge=1, le=1000)
    is_enabled: bool = True
    # mis. {"auth": "none"} (tanpa key), {"headers": {"X-Title": "gateway"}}
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderOut(_Out):
    id: uuid.UUID
    code: str
    kind: str
    display_name: str
    base_url: str | None
    api_key_env: str | None  # NAMA variabel env, bukan nilainya
    timeout_seconds: int
    max_concurrency: int
    is_enabled: bool
    config: dict[str, Any]
    updated_at: datetime


# ------------------------------------------------------------------- model
class _ModelFields(_In):
    upstream_name: str | None = Field(default=None, max_length=256)
    model_type: Literal["chat", "completion", "embedding", "image"] | None = None
    tier: Literal["light", "heavy"] | None = None
    supports_streaming: bool | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    supports_json_mode: bool | None = None
    supports_fim: bool | None = None
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    embedding_dimensions: int | None = Field(default=None, ge=1)
    device: Literal["remote", "gpu", "npu", "cpu"] | None = None
    runtime_backend: Literal["openvino_llm", "openvino_vlm", "openvino_diffusion"] | None = None
    artifact_path: str | None = None
    artifact_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    vram_mb: int | None = Field(default=None, ge=0)
    is_pinned: bool | None = None
    license: str | None = None
    input_cost_per_mtok: Decimal | None = Field(default=None, ge=0)
    output_cost_per_mtok: Decimal | None = Field(default=None, ge=0)
    cost_per_image: Decimal | None = Field(default=None, ge=0)
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class ModelCreate(_ModelFields):
    alias: str = Field(min_length=1, max_length=128)
    provider: str
    upstream_name: str = Field(min_length=1, max_length=256)  # type: ignore[assignment]
    model_type: Literal["chat", "completion", "embedding", "image"]  # type: ignore[assignment]


class ModelUpdate(_ModelFields):
    pass


class ModelOut(_Out):
    id: uuid.UUID
    alias: str
    provider_code: str
    upstream_name: str
    model_type: str
    tier: str
    supports_streaming: bool
    supports_tools: bool
    supports_vision: bool
    supports_json_mode: bool
    supports_fim: bool
    context_window: int | None
    max_output_tokens: int | None
    embedding_dimensions: int | None
    device: str
    runtime_backend: str | None
    artifact_path: str | None
    artifact_sha256: str | None
    vram_mb: int | None
    is_pinned: bool
    license: str | None
    input_cost_per_mtok: Decimal
    output_cost_per_mtok: Decimal
    cost_per_image: Decimal
    is_enabled: bool
    config: dict[str, Any]
    updated_at: datetime


# ------------------------------------------------------------------- route
class RouteTargetIn(_In):
    model_alias: str
    priority: int = Field(default=1, ge=1, le=100)
    weight: int = Field(default=1, ge=1, le=100)


class RouteCreate(_In):
    alias: str = Field(min_length=1, max_length=128)
    description: str | None = None
    strategy: Literal["priority", "round_robin"] = "priority"
    is_enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    targets: list[RouteTargetIn] = Field(min_length=1)


class RouteUpdate(_In):
    description: str | None = None
    strategy: Literal["priority", "round_robin"] | None = None
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None
    targets: list[RouteTargetIn] | None = Field(default=None, min_length=1)


class RouteOut(_Out):
    id: uuid.UUID
    alias: str
    description: str | None
    strategy: str
    is_enabled: bool
    config: dict[str, Any]
    targets: list[dict[str, Any]]
    updated_at: datetime


# ------------------------------------------------------------------- quota
class QuotaIn(_In):
    period: Literal["daily", "monthly"]
    max_requests: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)
    max_images: int | None = Field(default=None, ge=0)
    max_cost_usd: Decimal | None = Field(default=None, ge=0)
    is_enabled: bool = True


class QuotasSet(_In):
    quotas: list[QuotaIn] = Field(min_length=1, max_length=2)


class QuotaOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    period: str
    max_requests: int | None
    max_tokens: int | None
    max_images: int | None
    max_cost_usd: Decimal | None
    is_enabled: bool


# ------------------------------------------------------------------- query
class RequestFilter(BaseModel):
    project_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    status: str | None = None
    endpoint: str | None = None
    requested_model: str | None = None
    provider_code: str | None = None
    device: str | None = None
    caller_task: str | None = None
    caller_agent: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class UsageQuery(BaseModel):
    date_from: date
    date_to: date
    group_by: Literal["day", "project", "model", "provider"] = "day"
    project_id: uuid.UUID | None = None


class Page(BaseModel):
    data: list[dict[str, Any]]
    next_cursor: str | None = None


def snapshot(schema: type[BaseModel], obj: Any) -> dict[str, Any]:
    """Snapshot JSON-able (untuk respons & audit before/after)."""
    return schema.model_validate(obj).model_dump(mode="json")
