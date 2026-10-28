"""Router & fallback (TASK-13): `model` caller → daftar kandidat (route/izin/kapabilitas/provider
aktif/circuit breaker), lalu eksekusi berurutan dengan fallback yang aman."""

import asyncio
import collections
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from app.schemas.catalog import ModelConfig, RouteConfig
from app.schemas.common import AuthContext
from app.services.context import RequestCtx
from app.services.providers.base import BaseProvider
from app.utils.errors import (
    CapabilityNotSupported,
    GatewayError,
    ModelNotAllowed,
    ModelNotFound,
    ServiceUnavailable,
    UpstreamError,
    UpstreamTimeout,
)
from app.utils.helper import glob_match
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.registry import ProviderRegistry

log = get_logger(__name__)
T = TypeVar("T")

LOADED_CACHE_TTL_S = 5.0


class AllCandidatesFailed(UpstreamError):
    """Semua kandidat gagal (error retryable); detail di attempts."""

    code = "all_candidates_failed"
    retryable = False


@dataclass(frozen=True, slots=True)
class Capabilities:
    model_type: str = "chat"  # chat | completion | embedding | image
    tools: bool = False
    vision: bool = False
    json: bool = False
    stream: bool = False
    fim: bool = False
    image_edit: bool = False

    def missing(self, m: ModelConfig) -> list[str]:
        out = []
        if m.model_type != self.model_type:
            out.append(f"model_type={self.model_type}")
        checks = (
            (self.tools, m.supports_tools, "tools"),
            (self.vision, m.supports_vision, "vision"),
            (self.json, m.supports_json_mode, "json_mode"),
            (self.stream, m.supports_streaming, "stream"),
            (self.fim, m.supports_fim, "fim"),
            (self.image_edit, "image-to-image" in (m.config.get("tasks") or ()), "image_edit"),
        )
        out.extend(name for wanted, has, name in checks if wanted and not has)
        return out


class CircuitBreaker:
    """≥ threshold error retryable dalam window → model dipindah ke akhir daftar selama open_s
    (tidak dibuang)."""

    def __init__(
        self,
        threshold: int = 5,
        window_s: float = 60.0,
        open_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold, self.window_s, self.open_s, self.clock = threshold, window_s, open_s, clock
        self._errors: dict[str, collections.deque[float]] = {}
        self._open_until: dict[str, float] = {}

    def record_error(self, alias: str) -> None:
        now = self.clock()
        q = self._errors.setdefault(alias, collections.deque())
        q.append(now)
        while q and q[0] < now - self.window_s:
            q.popleft()
        if len(q) >= self.threshold:
            self._open_until[alias] = now + self.open_s
            q.clear()
            log.warning("circuit_open", model=alias, open_s=self.open_s)

    def record_success(self, alias: str) -> None:
        self._errors.pop(alias, None)

    def is_open(self, alias: str) -> bool:
        until = self._open_until.get(alias)
        if until is None:
            return False
        if self.clock() >= until:
            self._open_until.pop(alias, None)
            return False
        return True


class Router:
    def __init__(
        self,
        registry: "ProviderRegistry",
        *,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.clock = clock
        self._rr: dict[str, int] = collections.defaultdict(int)
        self._loaded: tuple[float, set[str]] = (float("-inf"), set())

    # ------------------------------------------------------------------ resolve
    async def resolve(
        self, requested: str, auth: AuthContext, need: Capabilities
    ) -> list[ModelConfig]:
        catalog = self.registry.catalog
        route = catalog.get_route(requested)
        if route is not None and route.is_enabled:
            aliases = self._order(route)
        elif requested in catalog.models:
            aliases = [requested]
        else:
            raise ModelNotFound(f"Model atau route '{requested}' tidak ditemukan")

        patterns = auth.allowed_models
        if not _allowed(requested, patterns):
            raise ModelNotAllowed(f"Project tidak diizinkan memakai '{requested}'", param="model")
        models = [m for a in aliases if (m := catalog.models.get(a)) is not None and m.is_enabled]
        allowed = [m for m in models if _allowed(m.alias, patterns)]
        if models and not allowed:
            raise ModelNotAllowed(
                f"Project tidak diizinkan memakai model mana pun di '{requested}'", param="model"
            )
        capable, missing = [], set()
        for m in allowed:
            lacks = need.missing(m)
            if lacks:
                missing.update(lacks)
            else:
                capable.append(m)
        if not capable:
            raise CapabilityNotSupported(
                f"Tidak ada model di '{requested}' yang mendukung: {', '.join(sorted(missing))}"
                if missing
                else f"'{requested}' tidak memiliki model aktif"
            )
        active = [m for m in capable if self.registry.provider_for(m) is not None]
        if not active:
            reasons = {
                m.provider_code: self.registry.disabled.get(m.provider_code, "tidak terdaftar")
                for m in capable
            }
            raise ServiceUnavailable(f"Provider untuk '{requested}' tidak aktif: {reasons}")

        if route is not None and route.config.get("prefer_loaded"):
            active = await self._prefer_loaded(route, active)
        # circuit breaker: kandidat bermasalah dipindah ke akhir, urutan relatif tetap
        return [m for m in active if not self.breaker.is_open(m.alias)] + [
            m for m in active if self.breaker.is_open(m.alias)
        ]

    def _order(self, route: RouteConfig) -> list[str]:
        targets = list(route.targets)  # sudah terurut priority
        if route.strategy != "round_robin" or len(targets) < 2:
            return [t.model_alias for t in targets]
        total = sum(max(t.weight, 0) for t in targets)
        if total <= 0:
            return [t.model_alias for t in targets]
        slot = self._rr[route.alias] % total
        self._rr[route.alias] += 1
        for i, t in enumerate(targets):
            slot -= max(t.weight, 0)
            if slot < 0:
                chosen = targets.pop(i)
                return [chosen.model_alias] + [x.model_alias for x in targets]
        return [t.model_alias for t in targets]  # pragma: no cover

    async def _prefer_loaded(
        self, route: RouteConfig, models: list[ModelConfig]
    ) -> list[ModelConfig]:
        """Di antara kandidat lokal dengan priority sama, yang sedang termuat didahulukan
        (hindari swap 7B tak perlu). Urutan priority berbeda tetap dihormati."""
        loaded = await self.loaded_models()
        priority = {t.model_alias: t.priority for t in route.targets}
        order = {m.alias: i for i, m in enumerate(models)}
        return sorted(
            models,
            key=lambda m: (
                priority.get(m.alias, 0),
                0 if (m.is_local and m.alias in loaded) else 1,
                order[m.alias],
            ),
        )

    async def loaded_models(self) -> set[str]:
        stamp, cached = self._loaded
        if self.clock() - stamp < LOADED_CACHE_TTL_S:
            return cached
        loaded: set[str] = set()
        for provider in self.registry.providers.values():
            fn = getattr(provider, "loaded_aliases", None)
            if fn is None:
                continue
            try:
                loaded |= set(await fn())
            except Exception as exc:  # noqa: BLE001 - preferensi saja, bukan syarat
                log.warning("runtime_status_unavailable", error=str(exc))
        self._loaded = (self.clock(), loaded)
        return loaded

    # ------------------------------------------------------------ eksekusi
    def provider(self, model: ModelConfig) -> BaseProvider:
        provider = self.registry.provider_for(model)
        if provider is None:
            raise ServiceUnavailable(f"Provider {model.provider_code} tidak aktif")
        return provider

    def first_token_timeout(self, model: ModelConfig) -> float:
        settings = self.registry.settings
        if model.is_local:
            return float(settings.local_first_token_timeout_s)
        return float(settings.first_token_timeout_s)

    def _failed(self, ctx: RequestCtx, model: ModelConfig, started: float, exc: Any) -> None:
        error = _as_gateway_error(exc, model)
        ctx.record(model, "error", started, error=error)
        if error.retryable:
            self.breaker.record_error(model.alias)
        log.warning(
            "attempt_failed",
            model=model.alias,
            error_type=error.code,
            retryable=error.retryable,
            error=error.message[:300],
        )
        if not error.retryable:
            raise error from (exc if isinstance(exc, BaseException) else None)

    async def run_with_fallback(
        self,
        ctx: RequestCtx,
        candidates: list[ModelConfig],
        call: Callable[[BaseProvider, ModelConfig], Awaitable[T]],
    ) -> tuple[T, ModelConfig]:
        """Coba kandidat berurutan; error retryable → kandidat berikutnya, non-retryable →
        langsung gagal. Setiap percobaan tercatat di ctx.attempts."""
        for model in candidates:
            started = time.perf_counter()
            try:
                provider = self.provider(model)
                timeout = max(float(provider.cfg.timeout_seconds), 1.0)
                result = await asyncio.wait_for(call(provider, model), timeout=timeout)
            except asyncio.CancelledError:
                ctx.record(model, "cancelled", started)
                raise
            except TimeoutError:
                self._failed(ctx, model, started, UpstreamTimeout(f"{model.alias}: timeout"))
                continue
            except Exception as exc:  # noqa: BLE001 - dipetakan & mungkin di-fallback
                self._failed(ctx, model, started, exc)
                continue
            ctx.record(
                model, "success", started, runtime_meta=getattr(result, "runtime_meta", None)
            )
            self.breaker.record_success(model.alias)
            return result, model
        raise _all_failed(ctx)

    async def open_stream(
        self,
        ctx: RequestCtx,
        candidates: list[ModelConfig],
        open_fn: Callable[[BaseProvider, ModelConfig], AsyncIterator[Any]],
    ) -> tuple[ModelConfig, Any, AsyncIterator[Any], float]:
        """Buka stream kandidat pertama yang berhasil memberi chunk pertama dalam
        first_token_timeout. Setelah itu TIDAK ada fallback (dikelola pemanggil)."""
        for model in candidates:
            started = time.perf_counter()
            iterator: AsyncIterator[Any] | None = None
            try:
                provider = self.provider(model)
                iterator = open_fn(provider, model).__aiter__()
                first = await asyncio.wait_for(
                    iterator.__anext__(), timeout=self.first_token_timeout(model)
                )
            except StopAsyncIteration:
                first = None
            except asyncio.CancelledError:
                await aclose_quietly(iterator)
                ctx.record(model, "cancelled", started)
                raise
            except TimeoutError:
                await aclose_quietly(iterator)
                limit = self.first_token_timeout(model)
                self._failed(
                    ctx,
                    model,
                    started,
                    UpstreamTimeout(f"{model.alias}: chunk pertama > {limit:g} s"),
                )
                continue
            except Exception as exc:  # noqa: BLE001
                await aclose_quietly(iterator)
                self._failed(ctx, model, started, exc)
                continue
            ctx.served_by = model
            assert iterator is not None
            return model, first, iterator, started
        raise _all_failed(ctx)


def _allowed(alias: str, patterns: tuple[str, ...]) -> bool:
    return any(glob_match(p, alias) for p in patterns)


def _as_gateway_error(exc: Any, model: ModelConfig) -> GatewayError:
    if isinstance(exc, GatewayError):
        return exc
    # adapter seharusnya sudah memetakan error; ini jaring pengaman
    log.error("unmapped_provider_error", model=model.alias, error=repr(exc))
    return UpstreamError(f"{model.alias}: {type(exc).__name__}: {exc}")


def _all_failed(ctx: RequestCtx) -> AllCandidatesFailed:
    summary = (
        "; ".join(f"{a.model.alias}: {a.error_type or a.status}" for a in ctx.attempts)
        or "tidak ada kandidat"
    )
    return AllCandidatesFailed(f"Semua kandidat gagal ({summary})")


async def aclose_quietly(iterator: Any) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        try:
            await aclose()
        except BaseException:  # noqa: BLE001
            pass
