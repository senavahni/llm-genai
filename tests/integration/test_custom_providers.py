"""Provider API pihak ketiga (selain OpenAI/Anthropic/Gemini) lewat Admin API: dibuat tanpa
ubah kode, dipakai lewat model & route, dihapus; key internal gateway tidak bisa dibocorkan."""

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AuditLog, Project
from app.services.key_service import key_service
from tests.fakes.fake_provider import FakeProvider

pytestmark = pytest.mark.integration

DEEPSEEK = {
    "code": "deepseek",
    "display_name": "DeepSeek",
    "adapter": "openai",
    "base_url": "https://api.deepseek.com/v1",
    "api_key_env": "DEEPSEEK_API_KEY",
}


@pytest.fixture
async def admin(api, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-deepseek-key")
    async with SessionLocal() as s:
        api.admin_key, _ = await key_service.create_key(
            s, project_id=None, name="adm", role="admin"
        )
    return api


async def test_add_custom_provider_model_route_and_call_it(admin):
    async with admin.client(admin.admin_key) as a:
        r = await a.post("/admin/providers", json=DEEPSEEK)
        assert r.status_code == 201, r.text
        assert r.json()["config"]["adapter"] == "openai" and r.json()["kind"] == "remote"
        assert (await a.post("/admin/providers", json=DEEPSEEK)).status_code == 409
        # banyak provider: kedua, tanpa key (mis. Ollama di LAN)
        r = await a.post(
            "/admin/providers",
            json={
                "code": "ollama-lan",
                "display_name": "Ollama LAN",
                "base_url": "http://192.168.1.50:11434/v1",
                "config": {"auth": "none"},
            },
        )
        assert r.status_code == 201, r.text
        r = await a.post(
            "/admin/models",
            json={
                "alias": "deepseek/chat",
                "provider": "deepseek",
                "upstream_name": "deepseek-chat",
                "model_type": "chat",
                "tier": "light",
                "supports_tools": True,
                "input_cost_per_mtok": "0.27",
                "output_cost_per_mtok": "1.10",
            },
        )
        assert r.status_code == 201, r.text
        r = await a.patch(
            "/admin/routes/smart",
            json={"targets": [{"model_alias": "deepseek/chat", "priority": 1}]},
        )
        assert r.status_code == 200, r.text
        status = (await a.get("/admin/providers")).json()["data"]
        assert {p["code"] for p in status} >= {"deepseek", "ollama-lan"}
        # project harus diizinkan memakai route DAN kandidatnya
        async with SessionLocal() as s:
            pid = await s.scalar(select(Project.id).where(Project.slug == "agent-a"))
        r = await a.put(
            f"/admin/projects/{pid}/allowed-models", json={"patterns": ["smart", "deepseek/*"]}
        )
        assert r.status_code == 200, r.text

    # adapter openai dipakai untuk kode provider baru (registry test: factory per adapter)
    deepseek = admin.providers["deepseek"]
    assert isinstance(deepseek, FakeProvider) and deepseek.cfg.code == "deepseek"
    assert "ollama-lan" in admin.app.state.registry.providers  # tanpa key tetap aktif
    async with admin.client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": [{"role": "user", "content": "hai"}]},
        )
    assert r.status_code == 200, r.text
    assert r.headers["x-gateway-provider"] == "deepseek"
    assert r.headers["x-gateway-model"] == "deepseek/chat"

    async with admin.client(admin.admin_key) as a:
        r = await a.delete("/admin/providers/deepseek")
        assert r.status_code == 409  # masih dipakai model
        assert (await a.delete("/admin/providers/ollama-lan")).json() == {"deleted": "ollama-lan"}
        assert (await a.delete("/admin/providers/openvino")).status_code == 409  # lokal
    async with SessionLocal() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert actions.count("provider.create") == 2 and "provider.delete" in actions


@pytest.mark.parametrize(
    ("patch", "param"),
    [
        ({"api_key_env": "GATEWAY_KEY_PEPPER"}, "api_key_env"),  # secret internal
        ({"api_key_env": "RUNTIME_TOKEN"}, "api_key_env"),
        ({"api_key_env": "DATABASE_URL"}, "api_key_env"),
        ({"api_key_env": None}, "api_key_env"),  # remote wajib key kecuali auth none
        ({"config": {"headers": {"Authorization": "Bearer x"}}}, "config.headers"),
        ({"config": {"auth": "basic"}}, "config.auth"),
    ],
)
async def test_secret_exfiltration_and_bad_config_rejected(admin, patch, param):
    async with admin.client(admin.admin_key) as a:
        r = await a.post("/admin/providers", json={**DEEPSEEK, **patch})
        assert r.status_code == 422, r.text
        assert r.json()["error"]["param"] == param
        # PATCH provider bawaan juga divalidasi
        if "api_key_env" in patch and patch["api_key_env"]:
            r = await a.patch("/admin/providers/openai", json=patch)
            assert r.status_code == 422


async def test_bad_code_adapter_url_are_400(admin):
    async with admin.client(admin.admin_key) as a:
        for bad in ({"code": "Deep Seek"}, {"adapter": "cohere"}, {"base_url": "ftp://x"}):
            assert (await a.post("/admin/providers", json={**DEEPSEEK, **bad})).status_code == 400
