import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_JSONB, Base, TimestampMixin, check_in, uuid_pk

if TYPE_CHECKING:
    from app.models.model import Model

PROVIDER_KINDS = ("remote", "local")


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (CheckConstraint(check_in("kind", PROVIDER_KINDS), name="kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True)  # openai|anthropic|gemini|...
    kind: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_env: Mapped[str | None] = mapped_column(String(64))  # NAMA variabel env, bukan nilai
    timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("120"))
    max_concurrency: Mapped[int] = mapped_column(Integer, server_default=text("16"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSONB)

    models: Mapped[list["Model"]] = relationship(back_populates="provider")
