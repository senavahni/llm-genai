"""Snapshot konfigurasi provider/model/route (immutable) yang dimuat dari DB oleh registry,
sehingga router dan usage tidak perlu query DB per request."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import Model, ModelRoute, Provider


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    id: uuid.UUID
    code: str
    kind: str  # remote | local
    display_name: str
    base_url: str | None
    api_key_env: str | None
    timeout_seconds: int = 120
    max_concurrency: int = 16
    is_enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: "Provider") -> "ProviderConfig":
        return cls(
            id=row.id,
            code=row.code,
            kind=row.kind,
            display_name=row.display_name,
            base_url=row.base_url,
            api_key_env=row.api_key_env,
            timeout_seconds=row.timeout_seconds,
            max_concurrency=row.max_concurrency,
            is_enabled=row.is_enabled,
            config=dict(row.config or {}),
        )


@dataclass(frozen=True, slots=True)
class ModelConfig:
    id: uuid.UUID
    alias: str
    provider_code: str
    upstream_name: str
    model_type: str  # chat | completion | embedding | image
    tier: str = "light"
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    supports_fim: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None
    embedding_dimensions: int | None = None
    device: str = "remote"
    runtime_backend: str | None = None
    vram_mb: int | None = None
    is_pinned: bool = False
    input_cost_per_mtok: Decimal = Decimal(0)
    output_cost_per_mtok: Decimal = Decimal(0)
    cost_per_image: Decimal = Decimal(0)
    is_enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.device != "remote"

    @classmethod
    def from_row(cls, row: "Model", provider_code: str) -> "ModelConfig":
        return cls(
            id=row.id,
            alias=row.alias,
            provider_code=provider_code,
            upstream_name=row.upstream_name,
            model_type=row.model_type,
            tier=row.tier,
            supports_streaming=row.supports_streaming,
            supports_tools=row.supports_tools,
            supports_vision=row.supports_vision,
            supports_json_mode=row.supports_json_mode,
            supports_fim=row.supports_fim,
            context_window=row.context_window,
            max_output_tokens=row.max_output_tokens,
            embedding_dimensions=row.embedding_dimensions,
            device=row.device,
            runtime_backend=row.runtime_backend,
            vram_mb=row.vram_mb,
            is_pinned=row.is_pinned,
            input_cost_per_mtok=row.input_cost_per_mtok,
            output_cost_per_mtok=row.output_cost_per_mtok,
            cost_per_image=row.cost_per_image,
            is_enabled=row.is_enabled,
            config=dict(row.config or {}),
        )


@dataclass(frozen=True, slots=True)
class RouteTarget:
    model_alias: str
    priority: int = 1
    weight: int = 1


@dataclass(frozen=True, slots=True)
class RouteConfig:
    alias: str
    strategy: str = "priority"
    description: str | None = None
    is_enabled: bool = True
    targets: tuple[RouteTarget, ...] = ()  # terurut priority

    @classmethod
    def from_row(cls, row: "ModelRoute") -> "RouteConfig":
        targets = sorted(
            (RouteTarget(t.model.alias, t.priority, t.weight) for t in row.targets),
            key=lambda t: (t.priority, t.model_alias),
        )
        return cls(
            alias=row.alias,
            strategy=row.strategy,
            description=row.description,
            is_enabled=row.is_enabled,
            targets=tuple(targets),
        )
