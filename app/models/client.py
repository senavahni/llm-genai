import secrets
import uuid
from sqlalchemy import Boolean, Column, Integer, String, Text, UUID
from sqlalchemy.orm import relationship
from app.models.base import BaseModel, TimestampMixin


class Client(BaseModel, TimestampMixin):
    """
    Mewakili project yang menggunakan API Gateway ini.
    Contoh: 'Project_A_Finance', 'Project_B_HR'
    """
    __tablename__ = 'clients'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_name = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True
    )
    api_key = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True
    )
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Rate limiting (opsional, untuk kontrol usage)
    rate_limit_per_minute = Column(Integer, default=60, nullable=False)
    rate_limit_per_day = Column(Integer, default=10000, nullable=False)

    # Relationships
    request_logs = relationship(
        'RequestLog',
        back_populates='client',
        cascade='all, delete-orphan',
        passive_deletes=True
    )
    generated_assets = relationship(
        'GeneratedAsset',
        back_populates='client',
        cascade='all, delete-orphan',
        passive_deletes=True
    )

    def __init__(self, project_name: str, description: str = None, **kwargs):
        super().__init__(**kwargs)
        self.project_name = project_name
        self.description = description
        self.api_key = self._generate_api_key()

    @staticmethod
    def _generate_api_key() -> str:
        """Generate API key yang aman dan unik"""
        # Format: llm_<random_string>
        return f"llm_{secrets.token_urlsafe(32)}"

    def __repr__(self):
        return f"<Client {self.project_name}>"