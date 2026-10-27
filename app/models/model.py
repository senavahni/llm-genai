import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.naming import conv

from app.models.base import EMPTY_JSONB, Base, TimestampMixin, check_in, uuid_pk

if TYPE_CHECKING:
    from app.models.provider import Provider

MODEL_TYPES = ("chat", "completion", "embedding", "image")
MODEL_TIERS = ("light", "heavy")
MODEL_DEVICES = ("remote", "gpu", "npu", "cpu")
RUNTIME_BACKENDS = ("llama_cpp_python", "llama_server", "openvino_diffusion", "openvino_embedding")


class Model(TimestampMixin, Base):
    __tablename__ = "models"
    __table_args__ = (
        CheckConstraint(check_in("model_type", MODEL_TYPES), name="model_type"),
        CheckConstraint(check_in("tier", MODEL_TIERS), name="tier"),
        CheckConstraint(check_in("device", MODEL_DEVICES), name="device"),
        CheckConstraint(check_in("runtime_backend", RUNTIME_BACKENDS), name="runtime_backend"),
        CheckConstraint(
            "device = 'remote' OR runtime_backend IS NOT NULL", name=conv("ck_local_has_backend")
        ),
        Index("ix_models_provider", "provider_id"),
        Index("ix_models_device", "device", postgresql_where=text("device <> 'remote'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT")
    )
    alias: Mapped[str] = mapped_column(String(128), unique=True)
    upstream_name: Mapped[str] = mapped_column(String(256))
    model_type: Mapped[str] = mapped_column(String(16))
    tier: Mapped[str] = mapped_column(String(16), server_default=text("'light'"))
    # kapabilitas
    supports_streaming: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    supports_tools: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    supports_vision: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    supports_json_mode: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    supports_fim: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    # runtime lokal
    device: Mapped[str] = mapped_column(String(8), server_default=text("'remote'"))
    runtime_backend: Mapped[str | None] = mapped_column(String(24))
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    vram_mb: Mapped[int | None] = mapped_column(Integer)
    is_pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    license: Mapped[str | None] = mapped_column(String(64))
    # biaya
    input_cost_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    output_cost_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    cost_per_image: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSONB)

    provider: Mapped["Provider"] = relationship(back_populates="models")

    @property
    def is_local(self) -> bool:
        return self.device != "remote"
