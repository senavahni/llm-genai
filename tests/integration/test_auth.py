import logging
import time
from datetime import timedelta

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select

from app.core.config import load_settings
from app.core.database import SessionLocal
from app.main import create_app
from app.models import ApiKey, Project
from app.models.project import ProjectAllowedModel
from app.routes import admin
from app.schemas.common import AuthContext
from app.services.key_service import key_service
from app.utils.auth import require_scope
from app.utils.helper import utcnow
from app.utils.logger import get_logger, setup_logging, shutdown_logging

pytestmark = pytest.mark.integration


def _app() -> FastAPI:
    app = create_app(load_settings())

    # path uji sendiri: /v1/chat/completions asli sudah ada (TASK-14)
    @app.post("/_test/chat")
    async def _chat(ctx: AuthContext = Depends(require_scope("chat"))) -> dict[str, str | None]:
        return {"project": ctx.project_slug, "prefix": ctx.key_prefix}

    # router uji dengan dependency yang sama persis dengan router /admin aplikasi
    test_admin = APIRouter(prefix="/admin", dependencies=admin.router.dependencies)

    @test_admin.get("/ping-test")
    async def _admin_ping() -> dict[str, str]:
        return {"ok": "admin"}

    app.include_router(test_admin)
    return app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _project(slug="agent-a", status="active") -> Project:
    async with SessionLocal() as s:
        p = Project(slug=slug, name=slug, status=status)
        s.add(p)
        await s.commit()
        return p


async def _key(project: Project | None, **kw) -> tuple[str, ApiKey]:
    async with SessionLocal() as s:
        return await key_service.create_key(
            s, project_id=project.id if project else None, name="k", **kw
        )


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def _chat(client, headers):
    return await client.post("/_test/chat", headers=headers, json={})


async def test_auth_context_carries_allowed_model_patterns(db):
    p = await _project()
    async with SessionLocal() as s:
        s.add_all(
            [
                ProjectAllowedModel(project_id=p.id, model_pattern="local/*"),
                ProjectAllowedModel(project_id=p.id, model_pattern="code"),
            ]
        )
        await s.commit()
    full_key, _ = await _key(p)
    ctx = await key_service.authenticate(full_key)
    assert ctx.allowed_models == ("code", "local/*")
    assert ctx.image_retention_days == 7
    admin_key, _ = await _key(None, role="admin")
    assert (await key_service.authenticate(admin_key)).allowed_models == ("*",)
    other = await _project("tanpa-pola")
    bare_key, _ = await _key(other)
    assert (await key_service.authenticate(bare_key)).allowed_models == ()


async def test_valid_key_bearer_and_x_api_key(db, client):
    p = await _project()
    full_key, key = await _key(p)
    r = await _chat(client, _bearer(full_key))
    assert r.status_code == 200, r.text
    assert r.json() == {"project": "agent-a", "prefix": key.key_prefix}
    r = await _chat(client, {"x-api-key": full_key})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer lgw_abcdefgh_" + "a" * 43},  # format ok, tidak ada di DB
        {"Authorization": "Bearer not-a-key"},
    ],
)
async def test_missing_or_unknown_key_is_401(db, client, headers):
    r = await _chat(client, headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


async def test_wrong_secret_with_valid_prefix_is_401(db, client):
    p = await _project()
    full_key, _ = await _key(p)
    tampered = full_key[:-1] + ("A" if full_key[-1] != "A" else "B")
    r = await _chat(client, _bearer(tampered))
    assert r.status_code == 401


async def test_revoked_key_is_401_immediately(db, client):
    p = await _project()
    full_key, key = await _key(p)
    assert (await _chat(client, _bearer(full_key))).status_code == 200  # masuk cache
    async with SessionLocal() as s:
        await key_service.revoke_key(s, key.id, reason="test")
    r = await _chat(client, _bearer(full_key))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


async def test_revoked_elsewhere_rejected_after_ttl(db, client):
    """Revoke dari instance lain (tanpa invalidate): ditolak setelah TTL cache habis."""
    p = await _project()
    full_key, key = await _key(p)
    assert (await _chat(client, _bearer(full_key))).status_code == 200
    async with SessionLocal() as s:
        row = await s.get(ApiKey, key.id)
        row.status = "revoked"
        await s.commit()
    assert (await _chat(client, _bearer(full_key))).status_code == 200  # masih cache
    entry, expires = key_service._cache[key.key_prefix]
    assert expires - time.monotonic() <= 60
    key_service._cache[key.key_prefix] = (entry, time.monotonic() - 1)  # simulasikan TTL habis
    assert (await _chat(client, _bearer(full_key))).status_code == 401


async def test_expired_key_is_401(db, client):
    p = await _project()
    full_key, _ = await _key(p, expires_at=utcnow() - timedelta(seconds=1))
    assert (await _chat(client, _bearer(full_key))).status_code == 401


async def test_suspended_project_is_403(db, client):
    p = await _project(status="suspended")
    full_key, _ = await _key(p)
    r = await _chat(client, _bearer(full_key))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "project_suspended"


async def test_missing_scope_is_403(db, client):
    p = await _project()
    full_key, _ = await _key(p, scopes=["embeddings", "models:read"])
    r = await _chat(client, _bearer(full_key))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "scope_denied"


async def test_admin_routes_require_admin_role(db, client):
    p = await _project()
    client_key, _ = await _key(p)
    admin_key, _ = await _key(None, role="admin")
    r = await client.get("/admin/ping-test", headers=_bearer(client_key))
    assert r.status_code == 403
    r = await client.get("/admin/ping-test", headers=_bearer(admin_key))
    assert r.status_code == 200
    r = await client.get("/admin/ping-test")
    assert r.status_code == 401


async def test_rotate_key(db, client):
    p = await _project()
    old_key, old = await _key(p, scopes=["chat"], rpm_limit=5)
    async with SessionLocal() as s:
        new_key, new = await key_service.rotate_key(s, old.id)
    assert new.scopes == ["chat"] and new.rpm_limit == 5 and new.project_id == p.id
    assert (await _chat(client, _bearer(old_key))).status_code == 401
    assert (await _chat(client, _bearer(new_key))).status_code == 200


async def test_auth_context_limits_and_last_used(db):
    p = await _project()
    full_key, key = await _key(p, rpm_limit=7)
    ctx = await key_service.authenticate(full_key)
    assert ctx.rpm_limit == 7
    assert ctx.tpm_limit == load_settings().default_tpm_limit
    assert ctx.scopes == frozenset(key.scopes)
    await key_service.drain()
    async with SessionLocal() as s:
        last_used = (
            await s.execute(select(ApiKey.last_used_at).where(ApiKey.id == key.id))
        ).scalar_one()
    assert last_used is not None


async def test_cache_hit_is_fast_and_skips_db(db, monkeypatch):
    p = await _project()
    full_key, _ = await _key(p)
    await key_service.authenticate(full_key)  # isi cache

    def _no_db():
        raise AssertionError("DB tidak boleh dipanggil saat cache hit")

    monkeypatch.setattr(key_service, "_session_factory", _no_db)
    n = 200
    start = time.perf_counter()
    for _ in range(n):
        await key_service.authenticate(full_key)
    per_call_ms = (time.perf_counter() - start) * 1000 / n
    assert per_call_ms < 1.0


async def test_key_hash_never_logged_or_returned(db, client, tmp_path):
    setup_logging(load_settings(log_dir=str(tmp_path), app_env="prod"), console=False)
    try:
        p = await _project()
        full_key, key = await _key(p)
        r = await _chat(client, _bearer(full_key))
        get_logger("test").info("dump", api_key=repr(key), raw=full_key, key_hash=key.key_hash)
        logging.getLogger("x").warning("header Authorization: Bearer %s", full_key)
    finally:
        shutdown_logging()
    assert key.key_hash not in repr(key)
    assert key.key_hash not in r.text and full_key not in r.text
    for f in tmp_path.glob("*.log"):
        content = f.read_text(encoding="utf-8")
        assert key.key_hash not in content, f.name
        assert full_key not in content, f.name
    access = (tmp_path / "access.log").read_text(encoding="utf-8")
    assert key.key_prefix in access and "agent-a" in access
