import uuid

import httpx
import httpx2
import pytest

from app.core.config import load_settings
from app.core.registry import ProviderRegistry
from app.main import create_app
from app.schemas.catalog import ProviderConfig
from app.services.providers.local_runtime_provider import LocalRuntimeProvider

pytestmark = pytest.mark.integration


def _refused(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("refused", request=request)


async def test_ready_degraded_when_runtime_down(db):
    settings = load_settings()
    app = create_app(settings)
    registry = ProviderRegistry(
        settings, http=httpx2.AsyncClient(transport=httpx2.MockTransport(_refused))
    )
    cfg = ProviderConfig(
        id=uuid.uuid4(),
        code="openvino",
        kind="local",
        display_name="l",
        base_url="http://127.0.0.1:8100/v1",
        api_key_env="RUNTIME_TOKEN",
    )
    registry.providers = {"openvino": LocalRuntimeProvider(cfg, registry.http, settings)}
    registry.disabled = {"openai": "API key kosong"}
    app.state.registry = registry

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/health/ready")
    assert r.status_code == 200  # DB hidup → gateway tetap melayani remote provider
    body = r.json()
    assert body["status"] == "degraded" and body["db"] is True
    assert body["providers"]["openvino"]["ok"] is False
    assert body["providers"]["openai"]["ok"] is None
