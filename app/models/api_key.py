import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.naming import conv

from app.models.base import Base, CreatedAtMixin, check_in, uuid_pk

if TYPE_CHECKING:
    from app.models.project import Project

KEY_ROLES = ("admin", "client")
KEY_STATUSES = ("active", "revoked")
VALID_SCOPES = ("chat", "completions", "embeddings", "images", "models:read", "usage:read")
DEFAULT_SCOPES_SQL = "ARRAY[" + ",".join(f"'{s}'" for s in VALID_SCOPES) + "]::text[]"


class ApiKey(CreatedAtMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(check_in("role", KEY_ROLES), name="role"),
        CheckConstraint(check_in("status", KEY_STATUSES), name="status"),
        CheckConstraint(
            "role = 'admin' OR project_id IS NOT NULL", name=conv("ck_client_has_project")
        ),
        Index("ix_api_keys_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), server_default=text("'client'"))
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(CHAR(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text(DEFAULT_SCOPES_SQL))
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    tpm_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    expires_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id"))

    project: Mapped["Project | None"] = relationship(back_populates="api_keys")

    def __repr__(self) -> str:  # key_hash sengaja tidak ditampilkan
        return f"ApiKey(id={self.id}, prefix={self.key_prefix!r}, role={self.role!r})"
