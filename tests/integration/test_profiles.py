"""Profil operasional (scripts/profiles/*.yaml) diterapkan ke DB dengan audit; seed --update-local
tidak mengaktifkan kembali model yang dinonaktifkan profil."""

import pytest
import yaml
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import AuditLog, Model, ModelRoute, ModelRouteTarget, Provider
from scripts._seedfile import load_seed
from tests.integration.conftest import ROOT, _manage

pytestmark = pytest.mark.integration
PROFILES = ROOT / "scripts" / "profiles"


def _profile(name: str) -> dict:
    return yaml.safe_load((PROFILES / f"{name}.yaml").read_text(encoding="utf-8"))


async def _state() -> tuple[dict[str, bool], dict[str, tuple[bool, list[tuple[str, int]]]]]:
    async with SessionLocal() as s:
        models = dict((await s.execute(select(Model.alias, Model.is_enabled))).all())
        routes = {}
        for route in (await s.execute(select(ModelRoute))).scalars():
            rows = await s.execute(
                select(Model.alias, ModelRouteTarget.priority)
                .join(Model, Model.id == ModelRouteTarget.model_id)
                .where(ModelRouteTarget.route_id == route.id)
            )
            routes[route.alias] = (route.is_enabled, sorted(rows.all()))
    return models, routes


def test_full_profile_matches_seed_routes():
    seed = {
        r["alias"]: sorted((t["model"], t.get("priority", 1)) for t in r["targets"])
        for r in load_seed()["routes"]
    }
    full = {
        r["alias"]: sorted((t["model"], t.get("priority", 1)) for t in r["targets"])
        for r in _profile("full")["routes"]
    }
    assert {a: full[a] for a in full} == {a: seed[a] for a in full}


async def test_apply_ram16_then_full_roundtrip(db):
    manage = _manage()
    data = load_seed()
    async with SessionLocal() as s:
        await manage._seed(s, data, update_local=False)
    _, routes_before = await _state()

    async with SessionLocal() as s:
        assert await manage._apply_profile(s, _profile("ram16")) > 0
    models, routes = await _state()
    assert not models["local/qwen2.5-7b"] and not models["local/sd-1.5"]
    assert models["local/qwen2.5-coder-1.5b"] and models["local/qwen2-vl-2b"]
    assert ("local/qwen2.5-coder-1.5b", 1) in routes["code"][1]
    assert routes["image"][0] is False
    async with SessionLocal() as s:
        audits = await s.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action.like("%profile:ram16"))
        )
    assert audits == 8  # 3 model + 5 route yang berubah (autocomplete & vision sudah sesuai)
    # idempoten
    async with SessionLocal() as s:
        assert await manage._apply_profile(s, _profile("ram16")) == 0

    # seed --update-local tidak mengaktifkan kembali model yang dimatikan profil
    async with SessionLocal() as s:
        await manage._seed(s, data, update_local=True)
    models, _ = await _state()
    assert not models["local/qwen2.5-7b"]

    async with SessionLocal() as s:
        await manage._apply_profile(s, _profile("full"))
    models, routes = await _state()
    assert all(models[a] for a in models if a.startswith("local/"))
    assert routes == routes_before


async def test_remote_only_disables_runtime_and_local_routes(db):
    manage = _manage()
    async with SessionLocal() as s:
        await manage._seed(s, load_seed(), update_local=False)
        await manage._apply_profile(s, _profile("remote-only"))
    models, routes = await _state()
    assert not any(on for alias, on in models.items() if alias.startswith("local/"))
    assert all(not routes[a][0] for a in ("local", "autocomplete", "image"))
    for alias in ("fast", "smart", "code", "vision"):
        enabled, targets = routes[alias]
        assert enabled and targets and all(not m.startswith("local/") for m, _ in targets)
    async with SessionLocal() as s:
        runtime_on = await s.scalar(select(Provider.is_enabled).where(Provider.code == "openvino"))
    assert runtime_on is False
    # kembali ke profil 2 model kecil: runtime & model kecil hidup lagi
    async with SessionLocal() as s:
        await manage._apply_profile(s, _profile("ram16"))
        runtime_on = await s.scalar(select(Provider.is_enabled).where(Provider.code == "openvino"))
    models, _ = await _state()
    assert runtime_on and models["local/qwen2-vl-2b"] and models["local/qwen2.5-coder-1.5b"]


async def test_invalid_profile_rejected_without_changes(db):
    manage = _manage()
    async with SessionLocal() as s:
        await manage._seed(s, load_seed(), update_local=False)
    before = await _state()
    bad = {
        "name": "rusak",
        "models": {"local/qwen2.5-7b": {"is_enabled": False}},
        "routes": [{"alias": "fast", "targets": [{"model": "local/qwen2.5-7b"}]}],
    }
    async with SessionLocal() as s:
        with pytest.raises(SystemExit, match="model nonaktif"):
            await manage._apply_profile(s, bad)
    async with SessionLocal() as s:
        with pytest.raises(SystemExit, match="tidak boleh"):
            await manage._apply_profile(s, {"models": {"local/sd-1.5": {"vram_mb": 1}}})
    assert await _state() == before
