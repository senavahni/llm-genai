"""Retensi data & maintenance (TASK-19). Semua purge berjalan per batch dengan commit per batch
(lock singkat; request baru tetap tercatat). `usage_daily` tidak pernah dihapus. Cache compile
OpenVINO TIDAK dibersihkan otomatis (compile ulang NPU mahal) — manual: manage.py clear-ov-cache."""

import asyncio
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import AuditLog, Request, RuntimeEvent
from app.models.image import GeneratedImage
from app.models.request import RequestPayload
from app.services import audit_service
from app.services.audit_service import Actor
from app.utils.helper import utcnow
from app.utils.logger import get_logger

log = get_logger(__name__)

ROW_BATCH = 5000
IMAGE_BATCH = 500
ANALYZE_THRESHOLD = 10_000
ORPHAN_MIN_AGE_S = 24 * 3600
DAILY_AT = (0, 30)  # 00:30 UTC


class MaintenanceService:
    def __init__(self, session_factory: Callable[[], AsyncSession] = SessionLocal) -> None:
        self._session_factory = session_factory

    @property
    def storage(self) -> Path:
        return Path(get_settings().storage_dir).resolve()

    async def _batched_delete(self, table: Any, key: Any, condition: Any, batch: int) -> int:
        """DELETE … WHERE key IN (SELECT key … LIMIT batch), diulang sampai habis."""
        total = 0
        while True:
            async with self._session_factory() as session:
                ids = select(key).where(condition).limit(batch).scalar_subquery()
                result = await session.execute(delete(table).where(key.in_(ids)))
                await session.commit()
            count = int(result.rowcount or 0)  # type: ignore[attr-defined]
            total += count
            if count < batch:
                return total
            await asyncio.sleep(0)  # beri giliran request lain di antara batch

    async def purge_payloads(self, batch: int = ROW_BATCH) -> int:
        return await self._batched_delete(
            RequestPayload,
            RequestPayload.request_id,
            RequestPayload.expires_at < utcnow(),
            batch,
        )

    async def purge_requests(self, days: int | None = None, batch: int = ROW_BATCH) -> int:
        """Cascade ke attempts, payload, baris generated_images (file yatim dibersihkan
        purge_orphan_image_files)."""
        cutoff = utcnow() - timedelta(days=days or get_settings().request_retention_days)
        return await self._batched_delete(Request, Request.id, Request.created_at < cutoff, batch)

    async def purge_audit(self, days: int | None = None, batch: int = ROW_BATCH) -> int:
        cutoff = utcnow() - timedelta(days=days or get_settings().audit_retention_days)
        return await self._batched_delete(
            AuditLog, AuditLog.id, AuditLog.created_at < cutoff, batch
        )

    async def purge_runtime_events(self, days: int | None = None, batch: int = ROW_BATCH) -> int:
        cutoff = utcnow() - timedelta(days=days or get_settings().runtime_event_retention_days)
        return await self._batched_delete(
            RuntimeEvent, RuntimeEvent.id, RuntimeEvent.created_at < cutoff, batch
        )

    async def purge_images(self, batch: int = IMAGE_BATCH) -> int:
        """Gambar kedaluwarsa: hapus file (thread) lalu barisnya. File hilang tetap menghapus
        baris (WARNING). Folder tanggal yang kosong ikut dihapus."""
        root = self.storage
        total = 0
        while True:
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        select(GeneratedImage.id, GeneratedImage.file_path)
                        .where(GeneratedImage.expires_at < utcnow())
                        .limit(batch)
                    )
                ).all()
                if not rows:
                    return total
                await asyncio.to_thread(self._remove_files, root, [p for _, p in rows])
                await session.execute(
                    delete(GeneratedImage).where(GeneratedImage.id.in_([i for i, _ in rows]))
                )
                await session.commit()
            total += len(rows)
            if len(rows) < batch:
                return total

    @staticmethod
    def _remove_files(root: Path, rel_paths: list[str]) -> None:
        parents = set()
        for rel in rel_paths:
            path = (root / rel).resolve()
            if not path.is_relative_to(root):
                log.warning("image_path_outside_storage", path=rel)
                continue
            if path.exists():
                path.unlink()
            else:
                log.warning("image_file_missing_on_purge", path=rel)
            parents.add(path.parent)
        for folder in parents:
            if folder != root and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

    async def purge_orphan_image_files(self, min_age_s: float = ORPHAN_MIN_AGE_S) -> int:
        """File di storage/images tanpa baris DB dan berumur > 1 hari → hapus."""
        root = self.storage
        images = root / "images"
        if not images.is_dir():
            return 0
        async with self._session_factory() as session:
            known = set((await session.execute(select(GeneratedImage.file_path))).scalars())

        def sweep() -> int:
            now = time.time()
            removed = 0
            for path in images.rglob("*"):
                if not path.is_file() or path.name.startswith("."):  # .gitkeep dsb.
                    continue
                rel = path.relative_to(root).as_posix()
                if rel not in known and now - path.stat().st_mtime > min_age_s:
                    path.unlink()
                    removed += 1
            for folder in sorted(images.iterdir(), reverse=True):
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
            return removed

        return await asyncio.to_thread(sweep)

    async def run_retention(
        self, actor: Actor | None = None, *, include_orphans: bool = True
    ) -> dict[str, Any]:
        started = time.perf_counter()
        counts = {
            "request_payloads": await self.purge_payloads(),
            "generated_images": await self.purge_images(),
            "requests": await self.purge_requests(),
            "audit_logs": await self.purge_audit(),
            "runtime_events": await self.purge_runtime_events(),
        }
        if include_orphans:
            counts["orphan_image_files"] = await self.purge_orphan_image_files()
        if counts["requests"] >= ANALYZE_THRESHOLD:
            async with self._session_factory() as session:
                await session.execute(text("ANALYZE requests"))
                await session.commit()
        result = {"counts": counts, "duration_ms": int((time.perf_counter() - started) * 1000)}
        log.info("retention.done", **counts, duration_ms=result["duration_ms"])
        async with self._session_factory() as session:
            audit_service.record(
                session, actor or Actor(None), "maintenance.retention", "system", None, None, result
            )
            await session.commit()
        return result


def seconds_until_daily_run(now: datetime | None = None) -> float:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    target = now.replace(hour=DAILY_AT[0], minute=DAILY_AT[1], second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def retention_forever() -> None:
    """Jadwal harian 00:30 UTC (task lifespan). File yatim hanya disapu hari Minggu (mingguan)."""
    while True:
        await asyncio.sleep(seconds_until_daily_run())
        try:
            weekly = datetime.now(UTC).weekday() == 6
            await maintenance_service.run_retention(include_orphans=weekly)
        except Exception as exc:  # noqa: BLE001 - coba lagi besok; jangan matikan gateway
            log.error("retention_failed", error=str(exc))


def clear_ov_cache(cache_dir: str | None = None) -> int:
    """Hapus isi cache compile OpenVINO (manual, setelah ganti versi OpenVINO/driver)."""
    root = Path(cache_dir or get_settings().ov_cache_dir).resolve()
    removed = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.name == ".gitkeep":
            continue
        if path.is_file():
            path.unlink()
            removed += 1
        elif path.is_dir() and not any(path.iterdir()):
            os.rmdir(path)
    return removed


maintenance_service = MaintenanceService()
