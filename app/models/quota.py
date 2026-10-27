import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, check_in, uuid_pk

QUOTA_PERIODS = ("daily", "monthly")


class Quota(TimestampMixin, Base):
    __tablename__ = "quotas"
    __table_args__ = (
        CheckConstraint(check_in("period", QUOTA_PERIODS), name="period"),
        UniqueConstraint("project_id", "period"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(16))
    max_requests: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(BigInteger)
    max_images: Mapped[int | None] = mapped_column(Integer)
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
