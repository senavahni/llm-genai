"""Admin Console: GET /admin/env-status khusus admin dan tidak pernah memuat nilai secret."""

import json

import pytest

from app.core.database import SessionLocal
from app.services.key_service import key_service

pytestmark = pytest.mark.integration


async def test_env_status_admin_only_and_redacted(api):
    async with SessionLocal() as s:
        admin_key, _ = await key_service.create_key(s, project_id=None, name="adm", role="admin")

    async with api.client() as c:
        assert (await c.get("/admin/env-status")).status_code == 403

    async with api.client(admin_key) as a:
        r = await a.get("/admin/env-status")
    assert r.status_code == 200
    body = r.json()
    names = {v["name"] for v in body["vars"]}
    assert {"DATABASE_URL", "GATEWAY_KEY_PEPPER", "RUNTIME_TOKEN", "OPENAI_API_KEY"} <= names
    assert {p["code"] for p in body["providers"]} >= {"openai", "anthropic"}

    settings = api.app.state.settings
    dumped = json.dumps(body)
    for secret in (
        settings.gateway_key_pepper.get_secret_value(),
        settings.runtime_token.get_secret_value(),
        settings.database_url,
    ):
        assert secret not in dumped
    assert all(v["value"] is None for v in body["vars"] if v["secret"])
