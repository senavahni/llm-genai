"""Pencatatan runtime_events: non-blocking (task terpisah, session DB baru). Gagal tulis DB →
fallback ke logs/runtime_events_fallback.jsonl agar event tidak hilang."""

import asyncio
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import RuntimeEvent
from app.utils.helper import utcnow
from app.utils.logger import get_logger
from runtime.core import metrics as runtime_metrics

log = get_logger("runtime.events")


class EventService:
    def __init__(
        self,
        fallback_path: Path,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
    ) -> None:
        self.fallback_path = fallback_path
        self._session_factory = session_factory
        self._tasks: set[asyncio.Task[None]] = set()
        self._file_lock = threading.Lock()

    def record(
        self,
        event: str,
        *,
        device: str,
        model_id: uuid.UUID | None = None,
        model_alias: str | None = None,
        reason: str | None = None,
        duration_ms: int | None = None,
        vram_used_mb: int | None = None,
        vram_budget_mb: int | None = None,
        request_id: str | uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "event": event,
            "device": device,
            "model_id": model_id,
            "model_alias": model_alias,
            "reason": reason,
            "duration_ms": duration_ms,
            "vram_used_mb": vram_used_mb,
            "vram_budget_mb": vram_budget_mb,
            "request_id": _as_uuid(request_id),
            "details": details or {},
        }
        fields = {k: v for k, v in values.items() if v not in (None, {}) and k != "event"}
        log.info("runtime_event", runtime_event=event, **fields)
        runtime_metrics.on_event(event, model_alias, device, duration_ms)
        task = asyncio.ensure_future(self._write(values))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _write(self, values: dict[str, Any]) -> None:
        try:
            async with self._session_factory() as session:
                session.add(RuntimeEvent(**values))
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("runtime_event_db_failed", error=str(exc), runtime_event=values["event"])
            await asyncio.to_thread(self._write_fallback, values)

    def _write_fallback(self, values: dict[str, Any]) -> None:
        line = orjson.dumps({**values, "created_at": utcnow()}, default=str)
        # beberapa thread bisa menulis bersamaan → serialisasi agar baris tidak tercampur
        with self._file_lock:
            self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with self.fallback_path.open("ab") as fh:
                fh.write(line + b"\n")

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
