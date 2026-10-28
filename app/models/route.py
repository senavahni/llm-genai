import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_JSONB, Base, TimestampMixin, check_in, uuid_pk
from app.models.model import Model

ROUTE_STRATEGIES = ("priority", "round_robin")


class ModelRoute(TimestampMixin, Base):
    __tablename__ = "model_routes"
    __table_args__ = (CheckConstraint(check_in("strategy", ROUTE_STRATEGIES), name="strategy"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    alias: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(16), server_default=text("'priority'"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # opsi routing, mis. {"prefer_loaded": true}
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSONB)

    targets: Mapped[list["ModelRouteTarget"]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ModelRouteTarget.priority",
    )


class ModelRouteTarget(Base):
    __tablename__ = "model_route_targets"

    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_routes.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"), primary_key=True
    )
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    weight: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))

    route: Mapped[ModelRoute] = relationship(back_populates="targets")
    model: Mapped[Model] = relationship()
