"""Katalog model lokal runtime. Single source of truth = tabel `models` (device <> 'remote')."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import Model
from app.utils.errors import ModelNotFound
from app.utils.logger import get_logger

log = get_logger("runtime.catalog")


@dataclass(frozen=True, slots=True)
class LocalModelSpec:
    alias: str
    upstream_name: str
    device: str  # gpu | npu
    runtime_backend: str
    model_type: str = "chat"
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    vram_mb: int = 0
    is_pinned: bool = False
    supports_fim: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    id: uuid.UUID | None = None

    @property
    def replicas(self) -> int:
        return max(1, int(self.config.get("replicas") or 1))

    @property
    def n_ctx(self) -> int | None:
        value = self.config.get("n_ctx")
        return int(value) if value else None

    def with_config(self, **changes: Any) -> "LocalModelSpec":
        return replace(self, config={**self.config, **changes})

    @classmethod
    def from_row(cls, row: Model) -> "LocalModelSpec":
        return cls(
            id=row.id,
            alias=row.alias,
            upstream_name=row.upstream_name,
            device=row.device,
            runtime_backend=row.runtime_backend or "",
            model_type=row.model_type,
            artifact_path=row.artifact_path,
            artifact_sha256=row.artifact_sha256,
            vram_mb=row.vram_mb or 0,
            is_pinned=row.is_pinned,
            supports_fim=row.supports_fim,
            config=dict(row.config or {}),
        )


class RuntimeCatalog:
    def __init__(self, session_factory: Callable[[], AsyncSession] = SessionLocal) -> None:
        self._session_factory = session_factory
        self.specs: dict[str, LocalModelSpec] = {}  # key = upstream_name (nama model di runtime)

    async def load(self) -> dict[str, LocalModelSpec]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Model).where(Model.device != "remote", Model.is_enabled.is_(True))
                    )
                )
                .scalars()
                .all()
            )
        self.specs = {r.upstream_name: LocalModelSpec.from_row(r) for r in rows}
        log.info("catalog_loaded", models=sorted(self.specs))
        return self.specs

    def set(self, specs: dict[str, LocalModelSpec]) -> None:
        self.specs = specs

    def get(self, name: str) -> LocalModelSpec:
        spec = self.specs.get(name)
        if spec is None:
            # izinkan juga alias gateway (mis. "local/qwen2.5-7b")
            spec = next((s for s in self.specs.values() if s.alias == name), None)
        if spec is None:
            raise ModelNotFound(f"Model lokal '{name}' tidak ada di katalog runtime")
        return spec
