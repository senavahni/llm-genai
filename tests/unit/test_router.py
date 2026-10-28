import asyncio
import uuid

import httpx2
import pytest

from app.core.config import get_settings
from app.core.registry import ProviderRegistry
from app.schemas.catalog import ModelConfig, ProviderConfig, RouteConfig, RouteTarget
from app.schemas.common import AuthContext
from app.schemas.unified import RuntimeMeta, UnifiedChatRequest, UnifiedMessage
from app.services.chat_service import ChatService
from app.services.context import Outcome, RequestCtx
from app.services.router_service import AllCandidatesFailed, Capabilities, CircuitBreaker, Router
from app.utils.errors import (
    CapabilityNotSupported,
    ModelBusy,
    ModelNotAllowed,
    ModelNotFound,
    ServiceUnavailable,
    UpstreamBadRequest,
    UpstreamError,
)
from scripts._seedfile import load_seed
from tests.fakes.fake_provider import FakeProvider

SEED = load_seed()
REQ = UnifiedChatRequest(messages=[UnifiedMessage(role="user", content="hai")])


def _model(item: dict) -> ModelConfig:
    keys = ModelConfig.__dataclass_fields__
    values = {k: v for k, v in item.items() if k in keys}
    return ModelConfig(id=uuid.uuid4(), provider_code=item["provider"], **values)


def _route(item: dict, **extra) -> RouteConfig:
    targets = sorted(
        (
            RouteTarget(t["model"], t.get("priority", 1), t.get("weight", 1))
            for t in item["targets"]
        ),
        key=lambda t: (t.priority, t.model_alias),
    )
    return RouteConfig(alias=item["alias"], targets=tuple(targets), **extra)


def _provider(code: str, **kw) -> FakeProvider:
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code=code,
        kind="local" if code == "openvino" else "remote",
        display_name=code,
        base_url=None,
        api_key_env=None,
        timeout_seconds=5,
    )
    return FakeProvider(cfg, httpx2.AsyncClient(), get_settings(), **kw)


def _registry(providers: dict[str, FakeProvider], *, models=None, routes=None, disabled=None):
    registry = ProviderRegistry(get_settings(), http=httpx2.AsyncClient())
    models = models or [_model(m) for m in SEED["models"]]
    routes = routes if routes is not None else [_route(r) for r in SEED["routes"]]
    registry.catalog.replace({m.alias: m for m in models}, {r.alias: r for r in routes})
    registry.providers = dict(providers)
    registry.disabled = dict(disabled or {})
    return registry


def _all_providers(**overrides) -> dict[str, FakeProvider]:
    codes = ("openai", "anthropic", "gemini", "openvino")
    return {c: overrides.get(c) or _provider(c) for c in codes}


def _auth(*patterns: str) -> AuthContext:
    return AuthContext(
        key_id=uuid.uuid4(),
        key_prefix="lgw_test",
        role="client",
        scopes=frozenset({"chat"}),
        project_id=uuid.uuid4(),
        project_slug="p",
        log_payloads=False,
        payload_retention_days=7,
        rpm_limit=100,
        tpm_limit=1000,
        allowed_models=patterns or ("*",),
    )


def _ctx(model="smart") -> RequestCtx:
    return RequestCtx(
        request_id=uuid.uuid4(), auth=_auth(), endpoint="chat.completions", requested_model=model
    )


CHAT = Capabilities()


# ------------------------------------------------------------------- resolve
@pytest.mark.parametrize(
    ("route", "need", "expected"),
    [
        ("fast", CHAT, ["local/qwen2.5-7b", "gemini/flash"]),
        ("smart", CHAT, ["anthropic/claude-sonnet", "openai/gpt-heavy", "local/qwen2.5-7b"]),
        ("local", CHAT, ["local/qwen2.5-7b", "local/qwen2.5-coder-7b"]),
        ("code", CHAT, ["local/qwen2.5-coder-7b", "anthropic/claude-sonnet", "local/qwen2.5-7b"]),
        ("autocomplete", Capabilities("completion", fim=True), ["local/qwen2.5-coder-1.5b"]),
        ("vision", Capabilities(vision=True), ["local/qwen2-vl-2b", "openai/gpt-light"]),
        ("image", Capabilities("image"), ["local/sd-1.5"]),
        ("image", Capabilities("image", image_edit=True), ["local/sd-1.5"]),
        ("embed-default", Capabilities("embedding"), ["openai/text-embedding-3-small"]),
    ],
)
async def test_default_routes_resolve_in_order(route, need, expected):
    router = Router(_registry(_all_providers()))
    assert [m.alias for m in await router.resolve(route, _auth(), need)] == expected


async def test_direct_model_and_unknown():
    router = Router(_registry(_all_providers()))
    [m] = await router.resolve("local/qwen2.5-7b", _auth(), CHAT)
    assert m.alias == "local/qwen2.5-7b"
    with pytest.raises(ModelNotFound):
        await router.resolve("tidak-ada", _auth(), CHAT)


async def test_glob_permissions():
    router = Router(_registry(_all_providers()))
    with pytest.raises(ModelNotAllowed):  # AC4
        await router.resolve("smart", _auth("local/*"), CHAT)
    with pytest.raises(ModelNotAllowed):  # tanpa pola = tolak semua
        await router.resolve("local/qwen2.5-7b", AuthContextNoPatterns(), CHAT)
    # route diizinkan tetapi kandidat disaring pola
    got = await router.resolve("smart", _auth("smart", "local/*"), CHAT)
    assert [m.alias for m in got] == ["local/qwen2.5-7b"]


def AuthContextNoPatterns() -> AuthContext:  # noqa: N802
    auth = _auth()
    return AuthContext(
        **{**{f: getattr(auth, f) for f in auth.__dataclass_fields__}, "allowed_models": ()}
    )


async def test_capability_filter_messages():
    router = Router(_registry(_all_providers()))
    with pytest.raises(CapabilityNotSupported, match="tools"):  # AC5
        await router.resolve("local/qwen2-vl-2b", _auth(), Capabilities(vision=True, tools=True))
    # route campuran: hanya kandidat yang mendukung yang tersisa
    got = await router.resolve("vision", _auth(), Capabilities(vision=True, tools=True))
    assert [m.alias for m in got] == ["openai/gpt-light"]
    with pytest.raises(CapabilityNotSupported, match="fim"):
        await router.resolve("fast", _auth(), Capabilities("completion", fim=True))


async def test_inactive_providers_dropped():
    providers = _all_providers()
    providers.pop("anthropic")
    router = Router(_registry(providers, disabled={"anthropic": "API key kosong"}))
    got = await router.resolve("smart", _auth(), CHAT)
    assert [m.alias for m in got] == ["openai/gpt-heavy", "local/qwen2.5-7b"]
    providers.pop("openvino")
    router = Router(_registry(providers, disabled={"anthropic": "x", "openvino": "x"}))
    with pytest.raises(ServiceUnavailable):
        await router.resolve("image", _auth(), Capabilities("image"))


async def test_round_robin_weighted_with_fallback_tail():
    models = [
        _model({"alias": a, "provider": "openai", "upstream_name": a, "model_type": "chat"})
        for a in ("m/a", "m/b")
    ]
    route = RouteConfig(
        alias="rr",
        strategy="round_robin",
        targets=(RouteTarget("m/a", 1, 3), RouteTarget("m/b", 1, 1)),
    )
    router = Router(_registry(_all_providers(), models=models, routes=[route]))
    firsts = [(await router.resolve("rr", _auth(), CHAT)) for _ in range(8)]
    assert [c[0].alias for c in firsts].count("m/a") == 6  # bobot 3:1
    assert all(len(c) == 2 for c in firsts)  # sisanya tetap jadi fallback


async def test_circuit_breaker_moves_model_to_end_then_recovers():
    now = [0.0]
    router = Router(_registry(_all_providers()), clock=lambda: now[0])
    router.breaker = CircuitBreaker(clock=lambda: now[0])
    for _ in range(5):
        router.breaker.record_error("anthropic/claude-sonnet")
    got = await router.resolve("smart", _auth(), CHAT)
    assert got[-1].alias == "anthropic/claude-sonnet" and len(got) == 3
    now[0] = 31
    got = await router.resolve("smart", _auth(), CHAT)
    assert got[0].alias == "anthropic/claude-sonnet"


async def test_prefer_loaded_within_same_priority():
    models = [_model(m) for m in SEED["models"]]
    route = RouteConfig(
        alias="local-any",
        targets=(
            RouteTarget("local/qwen2.5-7b", 1),
            RouteTarget("local/qwen2.5-coder-7b", 1),
            RouteTarget("openai/gpt-heavy", 2),
        ),
        config={"prefer_loaded": True},
    )
    router = Router(_registry(_all_providers(), models=models, routes=[route]))

    async def loaded():
        return {"local/qwen2.5-coder-7b"}

    router.loaded_models = loaded  # type: ignore[method-assign]
    got = await router.resolve("local-any", _auth(), CHAT)
    assert [m.alias for m in got] == [
        "local/qwen2.5-coder-7b",  # sedang termuat → hindari swap 7B
        "local/qwen2.5-7b",
        "openai/gpt-heavy",  # priority berbeda tetap dihormati
    ]


# ---------------------------------------------------------------- fallback
async def _execute(providers, model="smart", need=CHAT, req=REQ):
    router = Router(_registry(providers))
    ctx = _ctx(model)
    candidates = await router.resolve(model, ctx.auth, need)
    service = ChatService(router)
    return ctx, await service.execute(ctx, req, candidates)


async def test_fallback_on_retryable_error():  # AC1
    providers = _all_providers(anthropic=_provider("anthropic", mode="fail"))
    ctx, (resp, outcome) = await _execute(providers)
    assert resp.content == "Hello!" and len(ctx.attempts) == 2
    assert [a.status for a in ctx.attempts] == ["error", "success"]
    assert ctx.attempts[0].error_type == "upstream_error"
    assert ctx.served_by.alias == "openai/gpt-heavy"
    assert ctx.headers()["X-Gateway-Attempts"] == "2"


async def test_non_retryable_error_fails_immediately():  # AC2
    bad = _provider("anthropic", mode="fail", error=UpstreamBadRequest("400 dari provider"))
    providers = _all_providers(anthropic=bad)
    router = Router(_registry(providers))
    ctx = _ctx()
    with pytest.raises(UpstreamBadRequest):
        await ChatService(router).execute(ctx, REQ, await router.resolve("smart", ctx.auth, CHAT))
    assert providers["openai"].calls == 0 and len(ctx.attempts) == 1


async def test_all_candidates_failed():
    providers = {
        c: _provider(c, mode="fail") for c in ("openai", "anthropic", "gemini", "openvino")
    }
    router = Router(_registry(providers))
    ctx = _ctx()
    with pytest.raises(AllCandidatesFailed) as info:
        await ChatService(router).execute(ctx, REQ, await router.resolve("smart", ctx.auth, CHAT))
    assert len(ctx.attempts) == 3 and info.value.http_status == 502


async def test_local_model_busy_falls_back_with_device():  # AC6
    busy = _provider("openvino", mode="fail", error=ModelBusy("qwen2.5-coder-7b sibuk"))
    ctx, (resp, _) = await _execute(_all_providers(openvino=busy), model="code")
    first = ctx.attempts[0]
    assert first.model.alias == "local/qwen2.5-coder-7b"
    assert (first.error_type, first.device, first.status) == ("model_busy", "gpu", "error")
    assert ctx.served_by.alias == "anthropic/claude-sonnet"


async def test_runtime_meta_device_recorded():
    meta = RuntimeMeta(device="gpu", backend="openvino_llm", load_ms=1200, queue_ms=3)
    ctx, (_, outcome) = await _execute(
        _all_providers(openvino=_provider("openvino", runtime_meta=meta)), model="local"
    )
    assert ctx.attempts[0].device == "gpu" and outcome.runtime_meta.load_ms == 1200
    assert ctx.headers()["X-Gateway-Device"] == "gpu"


async def test_max_tokens_clamped_with_warning():
    req = REQ.model_copy(update={"max_tokens": 100_000})
    providers = _all_providers()
    ctx, _ = await _execute(providers, model="local/qwen2.5-7b", req=req)
    assert providers["openvino"].requests[-1].max_tokens == 4096
    assert ctx.headers()["X-Gateway-Warning"] == "max_tokens_clamped"


# ------------------------------------------------------------------- stream
async def _stream(providers, model="smart"):
    router = Router(_registry(providers))
    ctx = _ctx(model)
    outcome = Outcome()
    gen = ChatService(router).execute_stream(
        ctx, REQ, await router.resolve(model, ctx.auth, CHAT), outcome
    )
    return ctx, outcome, gen


async def test_stream_fallback_before_first_chunk_only():
    providers = _all_providers(anthropic=_provider("anthropic", mode="fail"))
    ctx, outcome, gen = await _stream(providers)
    chunks = [c async for c in gen]
    assert "".join(c.delta_content or "" for c in chunks) == "Hello!"
    assert [a.status for a in ctx.attempts] == ["error", "success"]
    assert outcome.usage.completion_tokens == 3 and outcome.ttft_ms is not None


async def test_stream_error_after_first_chunk_no_fallback():  # AC3
    providers = _all_providers(anthropic=_provider("anthropic", mode="fail_mid"))
    ctx, _, gen = await _stream(providers)
    got = []
    with pytest.raises(UpstreamError):
        async for chunk in gen:
            got.append(chunk)
    assert len(got) == 1 and providers["openai"].calls == 0
    assert [a.status for a in ctx.attempts] == ["error"]
    assert providers["anthropic"].closed


async def test_stream_first_token_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(get_settings(), "first_token_timeout_s", 0.05)
    slow = _provider("anthropic", mode="slow", delay_s=1.0)
    ctx, _, gen = await _stream(_all_providers(anthropic=slow))
    chunks = [c async for c in gen]
    assert chunks and ctx.attempts[0].error_type == "upstream_timeout"
    assert ctx.served_by.alias == "openai/gpt-heavy"


async def test_stream_cancel_records_cancelled():
    ctx, _, gen = await _stream(_all_providers())
    await gen.__anext__()
    await gen.aclose()
    assert [a.status for a in ctx.attempts] == ["cancelled"]
    await asyncio.sleep(0)
