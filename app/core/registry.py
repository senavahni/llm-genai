"""Registry provider + katalog model/route in-memory, dimuat dari DB saat startup dan reload()."""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, valid_provider_key_env
from app.core.database import SessionLocal
from app.models import Model, ModelRoute, ModelRouteTarget, Provider
from app.schemas.catalog import ModelConfig, ProviderConfig, RouteConfig
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.base import BaseProvider
from app.services.providers.gemini_provider import GeminiProvider
from app.services.providers.local_runtime_provider import LocalRuntimeProvider
from app.services.providers.openai_provider import OpenAIProvider
from app.utils.errors import ModelNotFound
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

log = get_logger(__name__)

# Adapter = format API upstream. Provider custom (DeepSeek, Groq, OpenRouter, Mistral, Ollama, ...)
# memilih salah satu lewat `providers.config.adapter`; tanpa itu adapter = kode provider (bawaan).
PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "openvino": LocalRuntimeProvider,
}
REMOTE_ADAPTERS = ("openai", "anthropic", "gemini")


def adapter_of(cfg: ProviderConfig) -> str:
    return str(cfg.config.get("adapter") or cfg.code)


def keyless(cfg: ProviderConfig) -> bool:
    """Provider remote tanpa API key (mis. Ollama/vLLM di LAN): `config.auth = "none"`."""
    return cfg.config.get("auth") == "none"


class ModelCatalog:
    """Snapshot `alias → ModelConfig` dan `route_alias → RouteConfig` (target terurut)."""

    def __init__(self) -> None:
        self.models: dict[str, ModelConfig] = {}
        self.routes: dict[str, RouteConfig] = {}

    def replace(self, models: dict[str, ModelConfig], routes: dict[str, RouteConfig]) -> None:
        # assignment atomik: pembaca tidak pernah melihat katalog setengah jadi
        self.models, self.routes = models, routes

    def get_model(self, alias: str) -> ModelConfig:
        model = self.models.get(alias)
        if model is None:
            raise ModelNotFound(f"Model '{alias}' tidak ditemukan")
        return model

    def get_route(self, alias: str) -> RouteConfig | None:
        return self.routes.get(alias)


class ProviderRegistry:
    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx2.AsyncClient | None = None,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
        provider_classes: dict[str, type[BaseProvider]] | None = None,
    ) -> None:
        self.settings = settings
        self._own_http = http is None
        self.http = http or httpx2.AsyncClient(
            timeout=None, limits=httpx2.Limits(max_connections=200, max_keepalive_connections=50)
        )
        self._session_factory = session_factory
        self._classes = provider_classes or PROVIDER_CLASSES
        self.providers: dict[str, BaseProvider] = {}
        self.provider_configs: dict[str, ProviderConfig] = {}
        self.disabled: dict[str, str] = {}  # code → alasan
        self.catalog = ModelCatalog()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------- load
    async def load(self) -> None:
        async with self._lock:
            async with self._session_factory() as session:
                provider_rows = (await session.execute(select(Provider))).scalars().all()
                model_rows = (await session.execute(select(Model))).scalars().all()
                route_rows = (
                    (
                        await session.execute(
                            select(ModelRoute).options(
                                selectinload(ModelRoute.targets).selectinload(
                                    ModelRouteTarget.model
                                )
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            configs = {p.code: ProviderConfig.from_row(p) for p in provider_rows}
            code_by_id = {p.id: p.code for p in provider_rows}
            await self._sync_providers(configs)

            models = {
                m.alias: ModelConfig.from_row(m, code_by_id[m.provider_id]) for m in model_rows
            }
            routes = {r.alias: RouteConfig.from_row(r) for r in route_rows}
            self.catalog.replace(models, routes)
            log.info(
                "registry_loaded",
                providers=sorted(self.providers),
                disabled=self.disabled,
                models=len(models),
                routes=len(routes),
            )

    async def _sync_providers(self, configs: dict[str, ProviderConfig]) -> None:
        new: dict[str, BaseProvider] = {}
        disabled: dict[str, str] = {}
        for code, cfg in configs.items():
            reason = self._disabled_reason(cfg)
            if reason:
                disabled[code] = reason
                continue
            current = self.providers.get(code)
            if current is not None and current.cfg == cfg:
                new[code] = current  # konfigurasi sama: pakai ulang instance (& semaphore)
                continue
            provider = self._class_for(cfg)(cfg, self.http, self.settings)  # type: ignore[misc]
            await provider.startup()
            new[code] = provider
        for code, old in self.providers.items():
            if new.get(code) is not old:
                await old.shutdown()
        for code, reason in disabled.items():
            if self.disabled.get(code) != reason:
                level = "info" if reason == "disabled di DB" else "warning"
                getattr(log, level)("provider_disabled", provider=code, reason=reason)
        self.providers, self.provider_configs, self.disabled = new, configs, disabled

    def _class_for(self, cfg: ProviderConfig) -> type[BaseProvider] | None:
        # kode dulu (bawaan / factory test), lalu adapter (provider custom)
        return self._classes.get(cfg.code) or self._classes.get(adapter_of(cfg))

    def _disabled_reason(self, cfg: ProviderConfig) -> str | None:
        if not cfg.is_enabled:
            return "disabled di DB"
        if self._class_for(cfg) is None:
            return (
                f"adapter '{adapter_of(cfg)}' tidak dikenal (pilihan: {', '.join(REMOTE_ADAPTERS)})"
            )
        if cfg.kind != "remote" or keyless(cfg):
            return None
        if not valid_provider_key_env(cfg.api_key_env):
            return f"api_key_env '{cfg.api_key_env}' tidak valid (harus berpola NAMA_API_KEY)"
        if not self.settings.provider_secret(cfg.api_key_env):
            return f"API key kosong ({cfg.api_key_env} tidak diisi di .env)"
        return None

    async def reload(self) -> None:
        """Dipanggil Admin API setelah perubahan provider/model/route."""
        await self.load()

    # ----------------------------------------------------------------- akses
    def get(self, code: str) -> BaseProvider | None:
        return self.providers.get(code)

    def provider_for(self, model: ModelConfig) -> BaseProvider | None:
        return self.providers.get(model.provider_code)

    async def close(self) -> None:
        for provider in self.providers.values():
            await provider.shutdown()
        self.providers = {}
        if self._own_http:
            await self.http.aclose()


async def load_registry(app: "FastAPI") -> ProviderRegistry:
    registry = ProviderRegistry(app.state.settings)
    app.state.registry = registry
    try:
        await registry.load()
    except Exception as exc:  # noqa: BLE001 - DB down saat start: gateway tetap hidup
        log.error("registry_load_failed", error=str(exc))
    return registry
