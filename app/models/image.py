import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, uuid_pk


class GeneratedImage(CreatedAtMixin, Base):
    __tablename__ = "generated_images"
    __table_args__ = (
        UniqueConstraint("request_id", "idx"),
        Index("ix_images_project_time", "project_id", text("created_at DESC")),
        Index("ix_images_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL")
    )
    idx: Mapped[int] = mapped_column(SmallInteger)  # urutan gambar dalam request
    file_path: Mapped[str] = mapped_column(Text)  # relatif terhadap STORAGE_DIR
    mime_type: Mapped[str] = mapped_column(String(32), server_default=text("'image/png'"))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    steps: Mapped[int | None] = mapped_column(SmallInteger)
    guidance_scale: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    sha256: Mapped[str] = mapped_column(CHAR(64))
    bytes: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime]
