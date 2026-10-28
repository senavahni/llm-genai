"""TASK-16: kuota project dengan DB nyata + integrasi rate limit/kuota di endpoint v1."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models import Project, Quota, UsageDaily
from app.services.quota_service import QuotaService
from app.utils.errors import QuotaExceeded

pytestmark = pytest.mark.integration


async def _project(**quota) -> uuid.UUID:
    async with SessionLocal() as s:
        p = Project(slug=f"q-{uuid.uuid4().hex[:8]}", name="q")
        s.add(p)
        await s.flush()
        s.add(Quota(project_id=p.id, period=quota.pop("period", "daily"), **quota))
        await s.commit()
        return p.id


async def _usage(project_id, day: date, *, requests=0, images=0, cost="0", tokens=0):
    async with SessionLocal() as s:
        await s.execute(
            insert(UsageDaily).values(
                day=day,
                project_id=project_id,
                model_alias="m",
                provider_code="p",
                request_count=requests,
                success_count=requests,
                image_count=images,
                cost_usd=Decimal(cost),
                prompt_tokens=tokens,
            )
        )
        await s.commit()


async def test_cost_quota_blocks_until_next_utc_day(db):  # AC3
    now = [datetime(2026, 10, 28, 20, 0, tzinfo=UTC)]
    svc = QuotaService(now=lambda: now[0], clock=lambda: 0.0)
    pid = await _project(max_cost_usd=Decimal("0.01"))
    await _usage(pid, now[0].date(), requests=3, cost="0.0099")
    await svc.check(pid)  # 0.0099 < 0.01
    svc.record(pid, cost=Decimal("0.0002"))  # request yang baru selesai (sebelum cache segar)
    with pytest.raises(QuotaExceeded) as info:
        await svc.check(pid)
    assert info.value.http_status == 429 and "cost_usd" in info.value.message
    assert info.value.headers["Retry-After"] == str(4 * 3600)  # sampai 00:00 UTC
    now[0] += timedelta(hours=5)  # hari berikutnya (UTC) → usage harian baru
    await svc.check(pid)


async def test_image_quota_counts_requested_n(db):  # AC3b
    now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    svc = QuotaService(now=lambda: now)
    pid = await _project(max_images=10)
    await _usage(pid, now.date(), requests=9, images=9)
    await svc.check(pid, images=1)
    with pytest.raises(QuotaExceeded, match="images 9\\+2/10"):
        await svc.check(pid, images=2)


async def test_monthly_requests_quota(db):
    now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    svc = QuotaService(now=lambda: now)
    pid = await _project(period="monthly", max_requests=5, max_tokens=None)
    await _usage(pid, date(2026, 10, 1), requests=3)
    await _usage(pid, date(2026, 9, 30), requests=50)  # bulan lalu tidak dihitung
    await svc.check(pid)
    await _usage(pid, date(2026, 10, 27), requests=2)
    svc.invalidate(pid)
    with pytest.raises(QuotaExceeded, match="bulanan"):
        await svc.check(pid)


async def test_v1_rate_limit_and_quota_headers(api):  # AC1 & AC4 end-to-end
    from sqlalchemy import update

    from app.models import ApiKey
    from app.services.key_service import key_service

    async with SessionLocal() as s:
        await s.execute(update(ApiKey).values(rpm_limit=2))
        await s.commit()
    key_service.invalidate()
    body = {"model": "smart", "messages": [{"role": "user", "content": "x"}]}
    async with api.client() as c:
        r = await c.post("/v1/chat/completions", json=body)
        assert r.status_code == 200 and r.headers["x-ratelimit-remaining-requests"] == "1"
        await c.post("/v1/chat/completions", json=body)
        r = await c.post("/v1/chat/completions", json=body)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
