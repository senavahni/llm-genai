"""TASK-15: pencatatan usage/biaya/request log dengan PostgreSQL nyata (llm_gateway_test)."""

import base64
import importlib.util
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml
from sqlalchemy import func, select, update

from app.core.config import load_settings
from app.core.database import SessionLocal
from app.main import create_app
from app.models import ApiKey, Project, Request, RequestAttempt, UsageDaily
from app.models.model import Model
from app.models.provider import Provider
from app.models.request import RequestPayload
from app.schemas.catalog import ModelConfig
from app.schemas.common import AuthContext
from app.schemas.unified import RuntimeMeta, Usage
from app.services.context import Outcome, RequestCtx
from app.services.key_service import key_service
from app.services.usage_service import UsageService, write_record
from app.utils.errors import ModelBusy, ServiceUnavailable, UpstreamError
from app.utils.helper import utcnow

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _manage():
    spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts" / "manage.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def catalog(db):
    data = yaml.safe_load((ROOT / "scripts" / "seed_models.yaml").read_text(encoding="utf-8"))
    async with SessionLocal() as s:
        await _manage()._seed(s, data, update_local=False)
        # harga contoh untuk uji biaya
        await s.execute(
            update(Model)
            .where(Model.alias == "anthropic/claude-sonnet")
            .values(input_cost_per_mtok=Decimal("3"), output_cost_per_mtok=Decimal("15"))
        )
        await s.commit()
        rows = (await s.execute(select(Model, Provider.code).join(Provider))).all()
    return {m.alias: ModelConfig.from_row(m, code) for m, code in rows}


@pytest.fixture
async def auth(db):
    async with SessionLocal() as s:
        project = Project(slug="proj-usage", name="P", log_payloads=False)
        s.add(project)
        await s.flush()
        key = ApiKey(project_id=project.id, name="k", key_prefix="lgw_usage001", key_hash="0" * 64)
        s.add(key)
        await s.commit()
        return AuthContext(
            key_id=key.id,
            key_prefix=key.key_prefix,
            role="client",
            scopes=frozenset({"chat"}),
            project_id=project.id,
            project_slug=project.slug,
            log_payloads=False,
            payload_retention_days=7,
            rpm_limit=100,
            tpm_limit=10_000,
            allowed_models=("*",),
        )


def _ctx(auth, endpoint="chat.completions", model="smart", **kw) -> RequestCtx:
    return RequestCtx(
        request_id=uuid.uuid4(), auth=auth, endpoint=endpoint, requested_model=model, **kw
    )


async def _row(request_id):
    async with SessionLocal() as s:
        req = await s.get(Request, request_id)
        attempts = (
            (
                await s.execute(
                    select(RequestAttempt)
                    .where(RequestAttempt.request_id == request_id)
                    .order_by(RequestAttempt.attempt_no)
                )
            )
            .scalars()
            .all()
        )
        return req, attempts


# ------------------------------------------------------------------- dasar
async def test_success_remote_with_fallback_and_cost(catalog, auth):
    usage = UsageService()
    ctx = _ctx(auth)
    await usage.start(ctx)
    req, _ = await _row(ctx.request_id)
    assert req.status == "pending"

    t = 0.0
    ctx.record(catalog["openai/gpt-heavy"], "error", t, error=UpstreamError("503"))
    ctx.record(catalog["anthropic/claude-sonnet"], "success", t)
    outcome = Outcome(
        usage=Usage(prompt_tokens=1234, completion_tokens=567),
        finish_reason="stop",
        upstream_model="claude-sonnet-5-5",
    )
    await usage.finish(ctx, outcome, status="success")
    req, attempts = await _row(ctx.request_id)
    assert (req.status, req.http_status, req.attempts, req.device) == ("success", 200, 2, "remote")
    assert req.provider_code == "anthropic" and req.total_tokens == 1801
    assert req.cost_usd == Decimal("0.01220700")  # 1234×3/1e6 + 567×15/1e6
    assert [a.status for a in attempts] == ["error", "success"]
    assert attempts[0].error_type == "upstream_error" and attempts[0].device == "remote"
    async with SessionLocal() as s:
        daily = (await s.execute(select(UsageDaily))).scalar_one()
    assert (daily.model_alias, daily.provider_code, daily.request_count) == (
        "anthropic/claude-sonnet",
        "anthropic",
        1,
    )
    assert daily.cost_usd == Decimal("0.01220700")


async def test_local_device_from_runtime_and_missing_meta(catalog, auth):
    usage = UsageService()
    ctx = _ctx(auth, model="local")
    await usage.start(ctx)
    meta = RuntimeMeta(device="gpu", backend="openvino_llm", load_ms=5200, queue_ms=12)
    ctx.record(catalog["local/qwen2.5-7b"], "success", 0.0, runtime_meta=meta)
    await usage.finish(ctx, Outcome(runtime_meta=meta), status="success")
    req, attempts = await _row(ctx.request_id)
    assert (req.device, req.load_ms, req.queue_ms) == ("gpu", 5200, 12)  # AC6
    assert attempts[0].device == "gpu"

    ctx = _ctx(auth, model="local")
    await usage.start(ctx)
    ctx.record(catalog["local/qwen2.5-7b"], "success", 0.0)
    await usage.finish(ctx, Outcome(), status="success")
    req, _ = await _row(ctx.request_id)
    assert req.device is None and req.tags["runtime_meta_missing"] is True


async def test_total_failure_counted_under_requested_model(catalog, auth):
    usage = UsageService()
    ctx = _ctx(auth, model="code")
    await usage.start(ctx)
    ctx.record(catalog["local/qwen2.5-coder-7b"], "error", 0.0, error=ModelBusy("sibuk"))
    ctx.served_by = None
    await usage.finish(ctx, None, status="error", error=UpstreamError("semua gagal"))
    req, attempts = await _row(ctx.request_id)
    assert (req.status, req.http_status, req.error_type) == ("error", 502, "upstream_error")
    assert attempts[0].error_type == "model_busy" and attempts[0].device == "gpu"
    async with SessionLocal() as s:
        daily = (await s.execute(select(UsageDaily))).scalar_one()
    assert (daily.model_alias, daily.provider_code, daily.error_count) == ("code", "none", 1)


# ------------------------------------------------------------ 100 request
async def test_hundred_mixed_requests_consistent(catalog, auth):  # AC1, AC2, AC7
    usage = UsageService()
    rnd = random.Random(7)
    kinds = ["success", "fallback", "error", "cancel", "image"]
    expected_attempts = {}
    for i in range(100):
        kind = kinds[i % len(kinds)]
        ctx = _ctx(auth, endpoint="images.generations" if kind == "image" else "chat.completions")
        await usage.start(ctx)
        outcome = Outcome(usage=Usage(prompt_tokens=rnd.randint(1, 500), completion_tokens=10))
        if kind == "fallback":
            ctx.record(catalog["anthropic/claude-sonnet"], "error", 0.0, error=UpstreamError("x"))
        if kind == "error":
            ctx.record(catalog["anthropic/claude-sonnet"], "error", 0.0, error=UpstreamError("x"))
            ctx.served_by = None
            await usage.finish(ctx, None, status="error", error=UpstreamError("gagal"))
        elif kind == "cancel":
            ctx.record(catalog["openai/gpt-heavy"], "cancelled", 0.0)
            await usage.finish(ctx, outcome, status="cancelled")
        elif kind == "image":
            ctx.record(
                catalog["local/sd-1.5"],
                "success",
                0.0,
                runtime_meta=RuntimeMeta(device="npu", backend="openvino_diffusion"),
            )
            outcome = Outcome(image_count=2, runtime_meta=ctx.attempts[-1].runtime_meta)
            await usage.finish(ctx, outcome, status="success")
        else:
            ctx.record(catalog["openai/gpt-heavy"], "success", 0.0)
            await usage.finish(ctx, outcome, status="success")
        expected_attempts[ctx.request_id] = len(ctx.attempts)

    async with SessionLocal() as s:
        pending = await s.scalar(
            select(func.count()).select_from(Request).where(Request.status == "pending")
        )
        assert pending == 0
        counts = dict(
            (
                await s.execute(
                    select(RequestAttempt.request_id, func.count()).group_by(
                        RequestAttempt.request_id
                    )
                )
            ).all()
        )
        images = await s.scalar(select(func.sum(UsageDaily.image_count)))
    assert counts == expected_attempts
    assert images == 40  # 20 request gambar × 2
    [row] = await usage.verify(utcnow().date())
    assert row["req_rows"] == row["agg_rows"] == 100 and row["diff"] == 0
    assert row["image_diff"] == 0


# ------------------------------------------------------------ DB mati
class _BrokenSession:
    async def __aenter__(self):
        raise ConnectionRefusedError("postgres mati")

    async def __aexit__(self, *exc):
        return False


async def test_db_down_start_503_and_finish_fallback_replay(catalog, auth, tmp_path):  # AC4
    broken = UsageService(session_factory=_BrokenSession, fallback_path=tmp_path / "fb.jsonl")
    with pytest.raises(ServiceUnavailable):
        await broken.start(_ctx(auth))

    good = UsageService(fallback_path=tmp_path / "fb.jsonl")
    ctx = _ctx(auth)
    await good.start(ctx)
    ctx.record(catalog["openai/gpt-heavy"], "success", 0.0)

    async def no_sleep(_):
        return None

    broken = UsageService(
        session_factory=_BrokenSession, fallback_path=tmp_path / "fb.jsonl", sleep=no_sleep
    )
    await broken.finish(ctx, Outcome(usage=Usage(prompt_tokens=5)), status="success")
    assert (tmp_path / "fb.jsonl").read_text().count("\n") == 1
    req, _ = await _row(ctx.request_id)
    assert req.status == "pending"

    assert await good.replay() == (1, 0)
    assert not (tmp_path / "fb.jsonl").exists()
    req, attempts = await _row(ctx.request_id)
    assert req.status == "success" and req.prompt_tokens == 5 and len(attempts) == 1


async def test_replay_is_idempotent(catalog, auth):
    usage = UsageService()
    ctx = _ctx(auth)
    await usage.start(ctx)
    ctx.record(catalog["openai/gpt-heavy"], "success", 0.0)
    record = usage.build_record(ctx, Outcome(), status="success")
    for _ in range(2):
        async with SessionLocal() as s:
            await write_record(s, record)
            await s.commit()
    async with SessionLocal() as s:
        assert await s.scalar(select(func.sum(UsageDaily.request_count))) == 1
        n_attempts = await s.scalar(select(func.count()).select_from(RequestAttempt))
    assert n_attempts == 1


# ------------------------------------------------------------ payload
async def test_payload_only_when_project_allows(catalog, auth):  # AC5
    usage = UsageService()
    big_image = base64.b64encode(b"x" * 200_000).decode()
    body = {
        "model": "smart",
        "messages": [{"role": "user", "content": "hai"}],
        "image": "data:image/png;base64," + big_image,
    }
    ctx = _ctx(auth, request_body=body)
    await usage.start(ctx)
    ctx.record(catalog["openai/gpt-heavy"], "success", 0.0)
    await usage.finish(ctx, Outcome(response_body={"content": "halo"}), status="success")

    logging_auth = AuthContext(
        **{**{f: getattr(auth, f) for f in auth.__dataclass_fields__}, "log_payloads": True}
    )
    ctx2 = _ctx(logging_auth, request_body=body)
    await usage.start(ctx2)
    ctx2.record(catalog["openai/gpt-heavy"], "success", 0.0)
    await usage.finish(ctx2, Outcome(response_body={"content": "halo"}), status="success")
    async with SessionLocal() as s:
        payloads = (await s.execute(select(RequestPayload))).scalars().all()
    assert [p.request_id for p in payloads] == [ctx2.request_id]
    assert payloads[0].request_body["image"].startswith("<image omitted:")
    assert payloads[0].response_body == {"content": "halo"}
    assert payloads[0].expires_at > utcnow() + timedelta(days=6)


# ------------------------------------------------------------ sweeper & verify
async def test_orphan_sweeper(catalog, auth):
    usage = UsageService()
    ctx = _ctx(auth, model="fast")
    await usage.start(ctx)
    async with SessionLocal() as s:
        await s.execute(
            update(Request)
            .where(Request.id == ctx.request_id)
            .values(created_at=utcnow() - timedelta(minutes=30))
        )
        await s.commit()
    assert await usage.sweep_orphans() == 1
    req, _ = await _row(ctx.request_id)
    assert (req.status, req.error_type) == ("error", "orphaned")
    [row] = await usage.verify((utcnow() - timedelta(minutes=30)).date())
    assert row["diff"] == 0


async def test_admin_verify_endpoint(catalog, auth):
    async with SessionLocal() as s:
        full_key, _ = await key_service.create_key(s, project_id=None, name="adm", role="admin")
    app = create_app(load_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get(
            "/admin/usage/verify",
            params={"day": date.today().isoformat()},
            headers={"Authorization": f"Bearer {full_key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["consistent"] is True
