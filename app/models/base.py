from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from app.extensions import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Mixin untuk menambahkan kolom created_at dan updated_at"""
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False
    )


class BaseModel(Base):
    """Base model dengan method umum. Persistensi lewat Session (Depends(get_db))."""
    __abstract__ = True

    def to_dict(self):
        """Convert model ke dictionary"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}