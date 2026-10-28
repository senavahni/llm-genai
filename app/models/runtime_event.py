import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_JSONB, Base, CreatedAtMixin, check_in

EVENT_DEVICES = ("gpu", "npu", "cpu")
RUNTIME_EVENTS = (
    "load",
    "unload",
    "evict",
    "oom",
    "compile",
    "load_failed",
    "device_error",
    "runtime_start",
    "runtime_stop",
    "queue_timeout",
)


class RuntimeEvent(CreatedAtMixin, Base):
    __tablename__ = "runtime_events"
    __table_args__ = (
        CheckConstraint(check_in("device", EVENT_DEVICES), name="device"),
        CheckConstraint(check_in("event", RUNTIME_EVENTS), name="event"),
        Index("ix_runtime_events_time", text("created_at DESC")),
        Index("ix_runtime_events_model", "model_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"))
    model_alias: Mapped[str | None] = mapped_column(String(128))  # snapshot nama untuk histori
    device: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(Text)  # mis. 'lru_evict_for:local/qwen2.5-7b'
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    vram_used_mb: Mapped[int | None] = mapped_column(Integer)  # setelah event
    vram_budget_mb: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[uuid.UUID | None]  # request pemicu (jika ada)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSONB)
