"""TASK-19: retensi data (DB nyata + file storage)."""

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core.database import SessionLocal
from app.models import AuditLog, Request, RuntimeEvent, UsageDaily
from app.models.image import GeneratedImage
from app.models.request import RequestPayload
from app.services.maintenance_service import MaintenanceService, seconds_until_daily_run
from app.utils.helper import utcnow

pytestmark = pytest.mark.integration


async def _count(model, *where) -> int:
    async with SessionLocal() as s:
        return int(await s.scalar(select(func.count()).select_from(model).where(*where)))


async def _bulk_requests(n: int, days_old: int) -> None:
    async with SessionLocal() as s:
        await s.execute(
            text(
                "INSERT INTO requests (id, endpoint, requested_model, status, created_at) "
                "SELECT gen_random_uuid(), 'chat.completions', 'smart', 'success', "
                "now() - make_interval(days => :d) FROM generate_series(1, :n)"
            ),
            {"n": n, "d": days_old},
        )
        await s.commit()


async def test_payloads_purged_usage_daily_untouched(api):  # AC1
    async with api.client() as c:
        for _ in range(2):
            await c.post(
                "/v1/chat/completions",
                json={"model": "smart", "messages": [{"role": "user", "content": "x"}]},
            )
    async with SessionLocal() as s:
        ids = (await s.execute(select(Request.id))).scalars().all()
        for rid in ids:
            s.add(
                RequestPayload(
                    request_id=rid,
                    request_body={"x": 1},
                    expires_at=utcnow() - timedelta(minutes=1),
                )
            )
        await s.commit()
    usage_before = await _count(UsageDaily)
    assert await MaintenanceService().purge_payloads() == 2
    assert await _count(RequestPayload) == 0
    assert await _count(UsageDaily) == usage_before and usage_before > 0
    assert await _count(Request) == 2  # request belum melewati retensi


async def test_expired_images_file_row_and_url_removed(api, tmp_path):  # AC1b
    async with api.client() as c:
        r = await c.post(
            "/v1/images/generations",
            json={"model": "image", "prompt": "rumah", "response_format": "url"},
        )
        path = r.json()["data"][0]["url"].removeprefix("http://gw")
        assert (await c.get(path)).status_code == 200
    async with SessionLocal() as s:
        [img] = (await s.execute(select(GeneratedImage))).scalars().all()
        await s.execute(update(GeneratedImage).values(expires_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    file = tmp_path / "storage" / img.file_path
    assert file.is_file()
    assert await MaintenanceService().purge_images() == 1
    assert not file.exists() and not file.parent.exists()  # folder tanggal kosong ikut dihapus
    assert await _count(GeneratedImage) == 0
    async with api.client() as c:
        assert (await c.get(path)).status_code == 404


async def test_old_requests_purged_in_batches_while_new_ones_recorded(db):  # AC2 (skala kecil)
    await _bulk_requests(12_000, days_old=200)
    await _bulk_requests(5, days_old=1)
    svc = MaintenanceService()
    batches = []
    original = svc._batched_delete

    async def spy(*args, **kwargs):
        start = time.perf_counter()
        result = await original(*args, **kwargs)
        batches.append(time.perf_counter() - start)
        return result

    svc._batched_delete = spy  # type: ignore[method-assign]
    assert await svc.purge_requests(days=180, batch=5000) == 12_000
    assert await _count(Request) == 5
    # tiap batch commit sendiri: insert request baru tidak menunggu purge selesai
    await _bulk_requests(1, days_old=0)
    assert await _count(Request) == 6
    assert batches[0] < 30


async def test_orphan_image_files_only_old_ones(db, monkeypatch, tmp_path):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    folder = tmp_path / "images" / "2026-01-01"
    folder.mkdir(parents=True)
    old, fresh = folder / "old.png", folder / "fresh.png"
    keep = tmp_path / "images" / ".gitkeep"
    for f, data in ((old, b"x"), (fresh, b"y"), (keep, b"")):
        f.write_bytes(data)
    past = time.time() - 3 * 24 * 3600
    os.utime(old, (past, past))
    os.utime(keep, (past, past))
    assert await MaintenanceService().purge_orphan_image_files() == 1
    assert not old.exists() and fresh.exists() and keep.exists()


async def test_run_retention_audit_events_and_counts(db, monkeypatch, tmp_path):
    from app.core.config import get_settings

    # sapu file yatim tidak boleh menyentuh storage dev (barisnya tidak ada di DB uji)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    async with SessionLocal() as s:
        s.add(
            AuditLog(
                action="project.create",
                entity_type="project",
                created_at=utcnow() - timedelta(days=800),
            )
        )
        s.add(RuntimeEvent(device="gpu", event="load", created_at=utcnow() - timedelta(days=100)))
        s.add(RuntimeEvent(device="gpu", event="load"))
        await s.commit()
    result = await MaintenanceService().run_retention()
    assert result["counts"]["audit_logs"] == 1 and result["counts"]["runtime_events"] == 1
    assert await _count(RuntimeEvent) == 1
    audits = await _count(AuditLog, AuditLog.action == "maintenance.retention")
    assert audits == 1


async def test_admin_retention_endpoint(api):
    from app.services.key_service import key_service

    async with SessionLocal() as s:
        admin_key, _ = await key_service.create_key(s, project_id=None, name="a", role="admin")
    async with api.client(admin_key) as c:
        r = await c.post("/admin/maintenance/retention")
    assert r.status_code == 200 and "requests" in r.json()["counts"]


def test_daily_schedule_0030_utc():
    assert seconds_until_daily_run(datetime(2026, 10, 28, 0, 0, tzinfo=UTC)) == 30 * 60
    assert seconds_until_daily_run(datetime(2026, 10, 28, 0, 30, tzinfo=UTC)) == 24 * 3600
    assert seconds_until_daily_run(datetime(2026, 10, 28, 23, 0, tzinfo=UTC)) == 90 * 60
