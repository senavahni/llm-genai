import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_JSONB, Base, CreatedAtMixin, check_in

if TYPE_CHECKING:
    from app.models.image import GeneratedImage

ENDPOINTS = ("chat.completions", "completions", "embeddings", "images.generations")
REQUEST_STATUSES = ("pending", "success", "error", "cancelled")
ATTEMPT_STATUSES = ("success", "error", "cancelled")


class Request(CreatedAtMixin, Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(check_in("endpoint", ENDPOINTS), name="endpoint"),
        CheckConstraint(check_in("status", REQUEST_STATUSES), name="status"),
        Index("ix_requests_project_time", "project_id", text("created_at DESC")),
        Index("ix_requests_key_time", "api_key_id", text("created_at DESC")),
        Index("ix_requests_status_time", "status", text("created_at DESC")),
        Index(
            "ix_requests_caller_task",
            "caller_task",
            postgresql_where=text("caller_task IS NOT NULL"),
        ),
        Index(
            "ix_requests_device_time",
            "device",
            text("created_at DESC"),
            postgresql_where=text("device IN ('gpu', 'npu', 'cpu')"),
        ),
        Index("brin_requests_created", "created_at", postgresql_using="brin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # = request_id, dibuat gateway
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    endpoint: Mapped[str] = mapped_column(String(64))
    requested_model: Mapped[str] = mapped_column(String(128))
    resolved_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL")
    )
    provider_code: Mapped[str | None] = mapped_column(String(32))
    upstream_model: Mapped[str | None] = mapped_column(String(256))
    device: Mapped[str | None] = mapped_column(String(8))  # remote|gpu|npu|cpu (aktual)
    is_stream: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    prompt_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cached_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    image_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), server_default=text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    load_ms: Mapped[int | None] = mapped_column(Integer)
    queue_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    client_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    caller_task: Mapped[str | None] = mapped_column(String(128))
    caller_agent: Mapped[str | None] = mapped_column(String(128))
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSONB)
    completed_at: Mapped[datetime | None]

    attempt_rows: Mapped[list["RequestAttempt"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RequestAttempt.attempt_no",
    )
    payload: Mapped["RequestPayload | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    images: Mapped[list["GeneratedImage"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class RequestAttempt(CreatedAtMixin, Base):
    __tablename__ = "request_attempts"
    __table_args__ = (
        CheckConstraint(check_in("status", ATTEMPT_STATUSES), name="status"),
        UniqueConstraint("request_id", "attempt_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL")
    )
    provider_code: Mapped[str] = mapped_column(String(32))
    device: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    request: Mapped[Request] = relationship(back_populates="attempt_rows")


class RequestPayload(CreatedAtMixin, Base):
    __tablename__ = "request_payloads"
    __table_args__ = (Index("ix_payloads_expires", "expires_at"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), primary_key=True
    )
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime]
