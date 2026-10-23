from sqlalchemy import (
    JSON, UUID, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
)
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class RequestLog(BaseModel):
    """
    Mencatat setiap request yang masuk ke API Gateway.
    Berguna untuk: audit, monitoring, debugging, billing.
    """
    __tablename__ = 'request_logs'

    id = Column(Integer, primary_key=True)
    client_id = Column(
        UUID(as_uuid=True),
        ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    client = relationship('Client', back_populates='request_logs')
    
    # Informasi Request
    endpoint = Column(String(200), nullable=False, index=True)
    method = Column(String(10), nullable=False)  # GET, POST, dll
    model_used = Column(String(100), nullable=False, index=True)
    
    # Status & Performance
    status_code = Column(Integer, nullable=False, index=True)
    latency_ms = Column(Integer, nullable=True)  # Waktu proses dalam ms
    tokens_used = Column(Integer, nullable=True)  # Untuk LLM text
    error_message = Column(Text, nullable=True)   # Jika error
    
    # Metadata tambahan (JSON)
    metadata_json = Column(JSON, nullable=True)  # Extra info (temperature, dll)
    
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Index composite untuk query performa
    __table_args__ = (
        Index('idx_client_endpoint', 'client_id', 'endpoint'),
        Index('idx_client_created', 'client_id', 'created_at'),
    )

    def __repr__(self):
        return f"<RequestLog {self.client_id} - {self.endpoint} [{self.status_code}]>"