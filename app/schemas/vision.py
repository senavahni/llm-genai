from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class VisionMessage(BaseModel):
    """Pesan untuk vision model (bisa contain text + image)"""
    role: Literal["system", "user", "assistant"]
    content: List[dict] = Field(
        ...,
        description="List content (text dan/atau image_url)"
    )

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if not v:
            raise ValueError('Content tidak boleh kosong')
        
        # Validasi format content
        for item in v:
            if 'type' not in item:
                raise ValueError('Setiap item content harus punya "type"')
            
            if item['type'] == 'text':
                if 'text' not in item:
                    raise ValueError('Content type "text" harus punya field "text"')
            elif item['type'] == 'image_url':
                if 'image_url' not in item:
                    raise ValueError('Content type "image_url" harus punya field "image_url"')
        
        return v


class VisionRequest(BaseModel):
    """Request untuk vision model (Qwen2-VL)"""
    model: str = Field(
        default="qwen2-vl-2b-instruct",
        description="Vision model yang digunakan"
    )
    messages: List[VisionMessage] = Field(
        ...,
        min_length=1,
        description="List pesan dengan text dan/atau gambar"
    )
    max_tokens: Optional[int] = Field(
        1024,
        ge=1,
        le=8192,
        description="Maksimal token output"
    )
    temperature: Optional[float] = Field(
        0.7,
        ge=0.0,
        le=2.0
    )


class VisionResponse(BaseModel):
    """Response dari vision model"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[dict]
    usage: dict