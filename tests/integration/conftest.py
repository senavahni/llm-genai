"""Fixture integrasi bersama: app gateway dengan katalog seed (DB llm_gateway_test) dan provider
palsu, dua project + key (`api.key` luas, `api.other_key` terbatas `local/*` & `image`)."""

import importlib.util
from pathlib import Path

import httpx
import httpx2
import openai
import pytest
import yaml

from app.core.config import get_settings, load_settings
from app.core.database import SessionLocal
from app.core.registry import ProviderRegistry
from app.main import create_app
from app.models import Project
from app.models.project import ProjectAllowedModel
from app.schemas.unified import RuntimeMeta
from app.services.key_service import key_service
from app.services.router_service import Router
from app.utils.streaming import drain_finishers
from tests.fakes.fake_provider import FakeProvider

ROOT = Path(__file__).resolve().parents[2]
GPU_META = RuntimeMeta(device="gpu", backend="openvino_llm", load_ms=0, queue_ms=1)


def _manage():
    spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts" / "manage.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


async def _project_key(slug: str, patterns: list[str], **project_kw) -> str:
    async with SessionLocal() as s:
        project = Project(slug=slug, name=slug, **project_kw)
        s.add(project)
        await s.flush()
        s.add_all(ProjectAllowedModel(project_id=project.id, model_pattern=p) for p in patterns)
        await s.commit()
        full_key, _ = await key_service.create_key(s, project_id=project.id, name="k")
    return full_key


class Api:
    def __init__(self, app, providers, key, other_key):
        self.app, self.providers, self.key, self.other_key = app, providers, key, other_key

    def client(self, key: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://gw",
            headers={"Authorization": f"Bearer {key or self.key}"},
            timeout=30,
        )

    def sdk(self) -> openai.AsyncOpenAI:
        http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app))
        return openai.AsyncOpenAI(
            api_key=self.key, base_url="http://gw/v1", http_client=http, max_retries=0
        )


@pytest.fixture
async def api(db, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))
    data = yaml.safe_load((ROOT / "scripts" / "seed_models.yaml").read_text(encoding="utf-8"))
    async with SessionLocal() as s:
        await _manage()._seed(s, data, update_local=False)
    # key palsu (bukan pola secret asli) agar provider remote tidak dinonaktifkan saat reload
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(env, "fake-test-key")
    settings = load_settings()
    app = create_app(settings)
    providers: dict[str, FakeProvider] = {}

    def factory(cfg, http, settings_):
        # instance per provider dipertahankan lintas registry.reload() (admin API), cfg diperbarui
        inst = providers.get(cfg.code)
        if inst is None:
            inst = providers[cfg.code] = FakeProvider(cfg, http, settings_)
            if cfg.code == "openvino":
                inst.runtime_meta = GPU_META
        inst.cfg = cfg
        return inst

    registry = ProviderRegistry(
        settings,
        http=httpx2.AsyncClient(),
        provider_classes={c: factory for c in ("openai", "anthropic", "gemini", "openvino")},
    )
    await registry.load()
    app.state.registry = registry
    app.state.router = Router(registry)
    key = await _project_key(
        "agent-a",
        [
            "smart",
            "local",
            "vision",
            "autocomplete",
            "image",
            "embed-default",
            "local/*",
            "anthropic/*",
            "openai/*",
        ],
    )
    other = await _project_key("agent-b", ["local/*", "image"])
    yield Api(app, providers, key, other)
    await drain_finishers()
