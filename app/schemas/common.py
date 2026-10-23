from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum


class ModelType(str, Enum):
    """Tipe model yang didukung"""
    TEXT = "text"
    VISION = "vision"
    IMAGE = "image"
    CODE = "code"


class ErrorResponse(BaseModel):
    """Format error response standar"""
    error: str = Field(..., description="Pesan error")
    code: str = Field(..., description="Kode error")
    details: Optional[Dict[str, Any]] = Field(None, description="Detail tambahan")
    request_id: Optional[str] = Field(None, description="ID request untuk tracking")


class UsageInfo(BaseModel):
    """Informasi penggunaan token (untuk LLM)"""
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class MetadataResponse(BaseModel):
    """Metadata umum untuk response"""
    model: str = Field(..., description="Model yang digunakan")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processing_time_ms: Optional[int] = Field(None, description="Waktu proses dalam ms")