import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_JSONB, Base, TimestampMixin, check_in, uuid_pk

if TYPE_CHECKING:
    from app.models.api_key import ApiKey

PROJECT_STATUSES = ("active", "suspended", "archived")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint(check_in("status", PROJECT_STATUSES), name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    log_payloads: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    payload_retention_days: Mapped[int] = mapped_column(Integer, server_default=text("7"))
    image_retention_days: Mapped[int] = mapped_column(Integer, server_default=text("7"))
    default_model: Mapped[str | None] = mapped_column(String(128))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=EMPTY_JSONB)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project", passive_deletes=True)
    allowed_models: Mapped[list["ProjectAllowedModel"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectAllowedModel(Base):
    __tablename__ = "project_allowed_models"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    model_pattern: Mapped[str] = mapped_column(String(128), primary_key=True)
