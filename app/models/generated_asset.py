import uuid
from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, func, UUID
)
from sqlalchemy.orm import relationship
from app.config import settings
from app.models.base import BaseModel


class GeneratedAsset(BaseModel):
    """
    Metadata file yang di-generate (gambar, audio, dll).
    File fisik disimpan di storages/, hanya metadata yang di-DB.
    """
    __tablename__ = 'generated_assets'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(
        UUID(as_uuid=True),
        ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    client = relationship('Client', back_populates='generated_assets')
    
    # Informasi File
    model_used = Column(String(100), nullable=False, index=True)
    prompt = Column(Text, nullable=True)  # Prompt yang dipakai
    negative_prompt = Column(Text, nullable=True)  # Untuk image gen
    
    # File details
    file_path = Column(String(500), nullable=False)  # Relative path
    file_name = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(50), nullable=False)  # image/png, image/jpeg
    
    # Image-specific metadata (nullable untuk model non-image)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    
    # Generation parameters (JSON)
    parameters_json = Column(JSON, nullable=True)  # steps, cfg_scale, seed, dll
    
    # Status
    is_public = Column(Boolean, default=False, nullable=False)  # Bisa diakses tanpa auth?
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Auto-delete
    
    # Timestamp
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Index untuk performa
    __table_args__ = (
        Index('idx_client_model', 'client_id', 'model_used'),
        Index('idx_created_model', 'created_at', 'model_used'),
    )

    @property
    def public_url(self) -> str:
        """Generate URL publik untuk file ini"""
        return f"{settings.PUBLIC_URL}/api/v1/files/{self.id}"

    def __repr__(self):
        return f"<GeneratedAsset {self.id} ({self.mime_type})>"