"""TASK-17: Admin API + audit log (DB nyata, provider palsu)."""

import json

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import AuditLog, Model, Request
from app.services.key_service import key_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def admin(api):
    async with SessionLocal() as s:
        full_key, _ = await key_service.create_key(s, project_id=None, name="adm", role="admin")
    api.admin_key = full_key
    return api


async def _audit_count() -> int:
    async with SessionLocal() as s:
        return int(await s.scalar(select(func.count()).select_from(AuditLog)))


async def _audits():
    async with SessionLocal() as s:
        return (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()


async def test_project_key_lifecycle_flow(admin):
    """buat project → set allowed models → buat key → pakai key → revoke → ditolak."""
    async with admin.client(admin.admin_key) as a:
        r = await a.post("/admin/projects", json={"slug": "riset-a", "name": "Riset A"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert (
            await a.post("/admin/projects", json={"slug": "Bad Slug", "name": "x"})
        ).status_code == 400
        assert (
            await a.post("/admin/projects", json={"slug": "riset-a", "name": "x"})
        ).status_code == 409
        # pola harus mencakup alias route DAN kandidatnya (TASK-13)
        patterns = ["smart", "anthropic/*", "openai/*"]
        r = await a.put(f"/admin/projects/{pid}/allowed-models", json={"patterns": patterns})
        assert r.json() == {"patterns": sorted(patterns)}
        assert (
            await a.put(f"/admin/projects/{pid}/allowed-models", json={"patterns": [" "]})
        ).status_code == 400
        r = await a.post(
            f"/admin/projects/{pid}/keys", json={"name": "dev", "scopes": ["chat", "models:read"]}
        )
        assert r.status_code == 201
        created = r.json()
        client_key, key_id = created["key"], created["id"]
        assert "key_hash" not in created
        assert (
            await a.post(f"/admin/projects/{pid}/keys", json={"name": "x", "scopes": ["root"]})
        ).status_code == 400

    body = {"model": "smart", "messages": [{"role": "user", "content": "hai"}]}
    async with admin.client(client_key) as c:
        assert (await c.post("/v1/chat/completions", json=body)).status_code == 200
        r = await c.post("/v1/chat/completions", json={**body, "model": "local"})
        assert r.status_code == 403  # di luar pola

    async with admin.client(admin.admin_key) as a:
        assert (await a.post(f"/admin/keys/{key_id}/revoke", json={})).status_code == 400
        r = await a.post(f"/admin/keys/{key_id}/revoke", json={"reason": "bocor"})
        assert r.json()["status"] == "revoked"
    async with admin.client(client_key) as c:
        assert (await c.post("/v1/chat/completions", json=body)).status_code == 401

    actions = [a.action for a in await _audits()]
    assert actions == ["project.create", "project.allowed_models.set", "key.create", "key.revoke"]
    for row in await _audits():  # AC2: tidak ada hash/secret di audit
        dump = json.dumps({"b": row.before, "a": row.after})
        assert "key_hash" not in dump and client_key not in dump
        assert row.actor_key_id is not None and row.ip is not None


async def test_rotate_suspend_archive(admin):
    async with admin.client(admin.admin_key) as a:
        pid = (
            await a.post(
                "/admin/projects",
                json={"slug": "p-two", "name": "P", "allowed_models": ["smart", "anthropic/*"]},
            )
        ).json()["id"]
        old = (await a.post(f"/admin/projects/{pid}/keys", json={"name": "k"})).json()
        new = (await a.post(f"/admin/keys/{old['id']}/rotate")).json()
        assert new["key"] != old["key"] and new["key_prefix"] != old["key_prefix"]
        keys = (await a.get(f"/admin/projects/{pid}/keys")).json()["data"]
        assert sorted(k["status"] for k in keys) == ["active", "revoked"]
        assert all("key" not in k for k in keys)

        body = {"model": "smart", "messages": [{"role": "user", "content": "x"}]}
        async with admin.client(new["key"]) as c:
            assert (await c.post("/v1/chat/completions", json=body)).status_code == 200
            r = await a.patch(f"/admin/projects/{pid}", json={"status": "suspended"})
            assert r.json()["status"] == "suspended"
            r = await c.post("/v1/chat/completions", json=body)  # cache auth di-invalidate
            assert r.status_code == 403 and r.json()["error"]["code"] == "project_suspended"
            r = await a.delete(f"/admin/projects/{pid}")
            assert r.json()["status"] == "archived" and r.json()["revoked_keys"]
            assert (await c.post("/v1/chat/completions", json=body)).status_code == 401


async def test_if_match_conflict(admin):
    async with admin.client(admin.admin_key) as a:
        p = (await a.post("/admin/projects", json={"slug": "p-im", "name": "P"})).json()
        r = await a.patch(
            f"/admin/projects/{p['id']}",
            json={"name": "Baru"},
            headers={"If-Match": p["updated_at"]},
        )
        assert r.status_code == 200
        r = await a.patch(
            f"/admin/projects/{p['id']}",
            json={"name": "Lagi"},
            headers={"If-Match": p["updated_at"]},
        )  # versi lama
        assert r.status_code == 409


async def test_model_route_changes_apply_without_restart(admin):  # AC3, AC5
    async with admin.client(admin.admin_key) as a:
        r = await a.post(
            "/admin/models",
            json={
                "alias": "openai/gpt-mini-baru",
                "provider": "openai",
                "upstream_name": "gpt-x",
                "model_type": "chat",
                "supports_tools": True,
                "input_cost_per_mtok": "0.1",
                "output_cost_per_mtok": "0.4",
            },
        )
        assert r.status_code == 201, r.text
        assert (
            await a.post(
                "/admin/models",
                json={
                    "alias": "smart",
                    "provider": "openai",
                    "upstream_name": "x",
                    "model_type": "chat",
                },
            )
        ).status_code == 409  # bentrok alias route
        r = await a.post(
            "/admin/routes",
            json={"alias": "hemat", "targets": [{"model_alias": "openai/gpt-mini-baru"}]},
        )
        assert r.status_code == 201
        assert (
            await a.post(
                "/admin/routes", json={"alias": "kosong", "targets": [{"model_alias": "tidak/ada"}]}
            )
        ).status_code == 400
        await a.put(
            f"/admin/projects/{await _project_id('agent-a')}/allowed-models",
            json={"patterns": ["hemat", "openai/*"]},
        )
    async with admin.client() as c:  # key project agent-a
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "hemat", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 200 and r.headers["x-gateway-model"] == "openai/gpt-mini-baru"
    async with admin.client(admin.admin_key) as a:
        r = await a.delete("/admin/models/openai/gpt-mini-baru")
        assert r.status_code == 409 and "hemat" in r.json()["error"]["message"]  # AC5
        r = await a.patch(
            "/admin/routes/hemat", json={"targets": [{"model_alias": "openai/gpt-light"}]}
        )
        assert r.json()["targets"][0]["model_alias"] == "openai/gpt-light"
        assert (await a.delete("/admin/models/openai/gpt-mini-baru")).status_code == 200
        assert (await a.delete("/admin/routes/hemat")).status_code == 200
    async with admin.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "hemat", "messages": [{"role": "user", "content": "x"}]},
        )
        assert r.status_code == 404


async def _project_id(slug: str) -> str:
    from app.models import Project

    async with SessionLocal() as s:
        return str((await s.execute(select(Project.id).where(Project.slug == slug))).scalar_one())


async def test_pin_over_budget_rejected_atomically(admin):  # AC1 (rollback) & AC6
    before = await _audit_count()
    async with admin.client(admin.admin_key) as a:
        r = await a.patch(
            "/admin/models/local/qwen2.5-7b", json={"is_pinned": True, "vram_mb": 9000}
        )
        assert r.status_code == 422
        assert "budget" in r.json()["error"]["message"]
        r = await a.patch("/admin/models/local/qwen2.5-7b", json={"device": "cpu"})
        assert r.status_code == 422
        r = await a.patch(
            "/admin/models/local/qwen2.5-7b", json={"artifact_path": "local_models/tidak-ada"}
        )
        assert r.status_code == 422
    assert await _audit_count() == before  # gagal → perubahan & audit ikut batal
    async with SessionLocal() as s:
        m = (await s.execute(select(Model).where(Model.alias == "local/qwen2.5-7b"))).scalar_one()
    assert (m.is_pinned, m.vram_mb, m.device) == (False, 4900, "gpu")


async def test_provider_update_and_test(admin):
    async with admin.client(admin.admin_key) as a:
        providers = (await a.get("/admin/providers")).json()["data"]
        assert all("fake-test-key" not in json.dumps(p) for p in providers)
        r = await a.patch("/admin/providers/openai", json={"timeout_seconds": 33})
        assert r.json()["timeout_seconds"] == 33
        r = await a.post("/admin/providers/openai/test")
        assert r.json()["ok"] is True


async def test_quotas_and_requests_cursor(admin):  # AC4
    pid = await _project_id("agent-a")
    async with admin.client(admin.admin_key) as a:
        r = await a.put(
            f"/admin/projects/{pid}/quotas",
            json={
                "quotas": [
                    {"period": "daily", "max_requests": 100},
                    {"period": "monthly", "max_images": 50},
                ]
            },
        )
        assert {q["period"] for q in r.json()["data"]} == {"daily", "monthly"}
    async with admin.client() as c:
        for i in range(5):
            await c.post(
                "/v1/chat/completions",
                json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
                headers={"X-Caller-Task": "research-42" if i % 2 == 0 else "lain"},
            )
    async with admin.client(admin.admin_key) as a:
        seen, cursor = [], None
        while True:
            params = {"caller_task": "research-42", "limit": 2}
            if cursor:
                params["cursor"] = cursor
            page = (await a.get("/admin/requests", params=params)).json()
            seen += [r["id"] for r in page["data"]]
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == 3
        async with SessionLocal() as s:
            expected = (
                (
                    await s.execute(
                        select(Request.id)
                        .where(Request.caller_task == "research-42")
                        .order_by(Request.created_at.desc(), Request.id.desc())
                    )
                )
                .scalars()
                .all()
            )
        assert seen == [str(x) for x in expected]
        detail = (await a.get(f"/admin/requests/{seen[0]}")).json()
        assert len(detail["attempt_rows"]) == 1
        usage = (await a.get("/admin/usage", params={"group_by": "model"})).json()
        assert usage["data"][0]["requests"] == 5
        audits = (await a.get("/admin/audit-logs", params={"action": "quota.set"})).json()
        assert len(audits["data"]) == 1
        assert (await a.get("/admin/requests", params={"limit": 500})).status_code == 400


async def test_runtime_admin_load_unload_audit(admin):  # AC7 (runtime palsu)
    calls = []

    async def fake_runtime_request(method, path, *, params=None, timeout=30.0):
        calls.append((method, path, params))
        if path == "/runtime/status":
            return 200, {
                "devices": {
                    "gpu": {
                        "models": [{"alias": "local/qwen2.5-7b", "pinned": False, "in_flight": 0}]
                    }
                }
            }
        if path.endswith("/load"):
            return 200, {"model": "local/qwen2.5-7b", "loaded": True, "load_ms": 5000}
        return 200, {"model": "local/qwen2.5-7b", "unloaded": True}

    admin.providers["openvino"].runtime_request = fake_runtime_request
    async with admin.client(admin.admin_key) as a:
        r = await a.post("/admin/runtime/models/local/qwen2.5-7b/load", params={"pin": "true"})
        assert r.json()["loaded"] is True
        assert calls[-1] == ("POST", "/runtime/models/local/qwen2.5-7b/load", {"pin": "true"})
        assert (await a.get("/admin/runtime/status")).json()["devices"]["gpu"]["models"]
        r = await a.post("/admin/runtime/models/local/qwen2.5-7b/unload")
        assert r.json()["unloaded"] is True
        r = await a.post("/admin/cache/reload")
        assert r.status_code == 200
    actions = [x.action for x in await _audits()]
    assert actions == ["runtime.load", "runtime.unload", "cache.reload"]


async def test_admin_requires_admin_role(admin):
    async with admin.client() as c:  # key client
        assert (await c.get("/admin/projects")).status_code == 403
