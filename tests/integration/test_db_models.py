import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models import (
    ApiKey,
    AuditLog,
    GeneratedImage,
    Model,
    ModelRoute,
    ModelRouteTarget,
    Project,
    Provider,
    Request,
    RequestAttempt,
    RequestPayload,
)
from app.utils.helper import new_request_id, utcnow

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def _load_manage():
    spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts" / "manage.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _seed_data():
    return yaml.safe_load((ROOT / "scripts" / "seed_models.yaml").read_text(encoding="utf-8"))


async def _make_chain(session):
    project = Project(slug="proj-a", name="Project A")
    session.add(project)
    await session.flush()
    key = ApiKey(project_id=project.id, name="k", key_prefix="lgw_aaaaaaaa", key_hash="0" * 64)
    session.add(key)
    await session.flush()
    req = Request(
        id=new_request_id(),
        project_id=project.id,
        api_key_id=key.id,
        endpoint="images.generations",
        requested_model="image",
        client_ip="127.0.0.1",
    )
    session.add(req)
    await session.flush()
    session.add_all(
        [
            RequestAttempt(
                request_id=req.id,
                attempt_no=1,
                provider_code="openvino",
                device="npu",
                status="success",
                latency_ms=10,
            ),
            RequestPayload(
                request_id=req.id,
                request_body={"prompt": "x"},
                expires_at=utcnow() + timedelta(days=7),
            ),
            GeneratedImage(
                request_id=req.id,
                project_id=project.id,
                idx=0,
                file_path="images/x.png",
                width=512,
                height=512,
                sha256="a" * 64,
                bytes=100,
                expires_at=utcnow() + timedelta(days=7),
            ),
        ]
    )
    await session.commit()
    return project, key, req


async def _count(session, model, *where):
    return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar()


async def test_insert_chain_and_defaults(db):
    async with SessionLocal() as s:
        project, key, req = await _make_chain(s)
        await s.refresh(key)
        await s.refresh(project)
        await s.refresh(req)
        assert key.scopes == [
            "chat",
            "completions",
            "embeddings",
            "images",
            "models:read",
            "usage:read",
        ]
        assert key.status == "active" and key.role == "client"
        assert project.status == "active" and project.image_retention_days == 7
        assert req.status == "pending" and req.image_count == 0 and req.created_at is not None


async def test_delete_request_cascades(db):
    async with SessionLocal() as s:
        _, _, req = await _make_chain(s)
        await s.execute(text("DELETE FROM requests WHERE id = :id"), {"id": req.id})
        await s.commit()
        assert await _count(s, RequestAttempt) == 0
        assert await _count(s, RequestPayload) == 0
        assert await _count(s, GeneratedImage) == 0


async def test_delete_project_cascades_keys_and_nulls_requests(db):
    async with SessionLocal() as s:
        project, _, req = await _make_chain(s)
        await s.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
        await s.commit()
        assert await _count(s, ApiKey) == 0
        row = (
            await s.execute(
                select(Request.project_id, Request.api_key_id).where(Request.id == req.id)
            )
        ).one()
        assert row == (None, None)
        img = (await s.execute(select(GeneratedImage.project_id))).scalar_one()
        assert img is None
        assert await _count(s, RequestAttempt) == 1


async def test_client_key_requires_project(db):
    async with SessionLocal() as s:
        s.add(
            ApiKey(
                project_id=None,
                name="x",
                role="client",
                key_prefix="lgw_bbbbbbbb",
                key_hash="0" * 64,
            )
        )
        with pytest.raises(IntegrityError, match="ck_client_has_project"):
            await s.commit()
        await s.rollback()
        s.add(
            ApiKey(
                project_id=None,
                name="admin",
                role="admin",
                key_prefix="lgw_cccccccc",
                key_hash="0" * 64,
            )
        )
        await s.commit()


async def test_local_model_without_backend_rejected(db):
    async with SessionLocal() as s:
        provider = Provider(code="llamacpp", kind="local", display_name="x")
        s.add(provider)
        await s.flush()
        s.add(
            Model(
                provider_id=provider.id,
                alias="local/x",
                upstream_name="x",
                model_type="chat",
                device="gpu",
            )
        )
        with pytest.raises(IntegrityError, match="ck_local_has_backend"):
            await s.commit()


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("requests", "endpoint", "chat"),
        ("requests", "status", "done"),
        ("models", "device", "tpu"),
        ("projects", "status", "deleted"),
    ],
)
async def test_check_constraints(db, table, column, value):
    async with SessionLocal() as s:
        provider = Provider(code="p", kind="remote", display_name="p")
        s.add(provider)
        await s.flush()
        values = {
            "requests": {"id": uuid.uuid4(), "endpoint": "completions", "requested_model": "m"},
            "models": {
                "provider_id": provider.id,
                "alias": "a",
                "upstream_name": "u",
                "model_type": "chat",
                "runtime_backend": "llama_cpp_python",
            },
            "projects": {"slug": "s", "name": "n"},
        }[table]
        values[column] = value
        cls = {"requests": Request, "models": Model, "projects": Project}[table]
        s.add(cls(**values))
        with pytest.raises(IntegrityError, match=f"ck_{table}_{column}"):
            await s.commit()


async def test_requests_indexes_exist(db):
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'requests'")
            )
        ).all()
    defs = dict(rows)
    for name in [
        "ix_requests_project_time",
        "ix_requests_key_time",
        "ix_requests_status_time",
        "ix_requests_caller_task",
        "ix_requests_device_time",
        "brin_requests_created",
    ]:
        assert name in defs
    assert "USING brin" in defs["brin_requests_created"]
    assert "WHERE" in defs["ix_requests_caller_task"]
    assert "created_at DESC" in defs["ix_requests_project_time"]


async def test_seed_idempotent_and_complete(db):
    manage = _load_manage()
    data = _seed_data()
    for _ in range(2):
        async with SessionLocal() as s:
            await manage._seed(s, data, update_local=False)

    async with SessionLocal() as s:
        assert await _count(s, Provider) == 5
        assert await _count(s, Model, Model.device != "remote") == 11
        assert await _count(s, ModelRoute) == 9
        n_targets = sum(len(r["targets"]) for r in data["routes"])
        assert await _count(s, ModelRouteTarget) == n_targets
        local = (
            await s.execute(
                select(Provider.base_url, Provider.api_key_env).where(Provider.code == "llamacpp")
            )
        ).one()
        assert local.api_key_env == "RUNTIME_TOKEN"
        assert local.base_url.endswith("/v1")
        coder = (
            await s.execute(select(Model).where(Model.alias == "local/qwen2.5-coder-1.5b"))
        ).scalar_one()
        assert coder.is_pinned and coder.supports_fim
        assert coder.config["source"]["hf_repo"]


async def test_seed_update_local_writes_audit(db):
    manage = _load_manage()
    data = _seed_data()
    async with SessionLocal() as s:
        await manage._seed(s, data, update_local=False)

    measured = next(m for m in data["models"] if m["alias"] == "local/qwen2.5-7b")
    measured["vram_mb"] = 5123
    measured["artifact_sha256"] = "b" * 64
    async with SessionLocal() as s:
        await manage._seed(s, data, update_local=True)
    async with SessionLocal() as s:
        model = (
            await s.execute(select(Model).where(Model.alias == "local/qwen2.5-7b"))
        ).scalar_one()
        assert model.vram_mb == 5123 and model.artifact_sha256 == "b" * 64
        audit = (await s.execute(select(AuditLog))).scalars().all()
        assert len(audit) == 1
        assert audit[0].actor_key_id is None
        assert audit[0].before["vram_mb"] == 5400 and audit[0].after["vram_mb"] == 5123
