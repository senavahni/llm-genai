import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageDaily(Base):
    """Agregat harian; upsert via INSERT ... ON CONFLICT DO UPDATE (akumulasi)."""

    __tablename__ = "usage_daily"
    __table_args__ = (Index("ix_usage_daily_project_day", "project_id", text("day DESC")),)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    image_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(16, 8), server_default=text("0"))
