from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator
from app.schemas.common import UsageInfo, MetadataResponse


class ChatMessage(BaseModel):
    """Pesan dalam chat"""
    role: Literal["system", "user", "assistant"] = Field(
        ...,
        description="Role pengirim pesan"
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="Isi pesan"
    )

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if not v.strip():
            raise ValueError('Content tidak boleh kosong atau hanya whitespace')
        return v.strip()


class ChatCompletionRequest(BaseModel):
    """Request untuk chat completion (OpenAI-compatible)"""
    model: str = Field(
        ...,
        description="Nama model yang akan digunakan",
        examples=["qwen2.5-7b-instruct", "qwen2.5-coder-7b-instruct", "gpt-4o", "claude-3-5-sonnet"]
    )
    messages: List[ChatMessage] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List pesan dalam percakapan"
    )
    temperature: Optional[float] = Field(
        0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        2048,
        ge=1,
        le=32000,
        description="Maksimal token yang di-generate"
    )
    top_p: Optional[float] = Field(
        0.9,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling"
    )
    stream: Optional[bool] = Field(
        False,
        description="Apakah response di-stream?"
    )
    stop: Optional[List[str]] = Field(
        None,
        max_length=4,
        description="Stop sequences"
    )

    @field_validator('messages')
    @classmethod
    def validate_messages(cls, v):
        if not any(msg.role == 'user' for msg in v):
            raise ValueError('Harus ada minimal satu pesan dengan role "user"')
        return v


class ChatCompletionChoice(BaseModel):
    """Pilihan response dari model"""
    index: int = Field(..., ge=0)
    message: ChatMessage
    finish_reason: Literal["stop", "length", "content_filter", "error"]


class ChatCompletionResponse(BaseModel):
    """Response chat completion (OpenAI-compatible)"""
    id: str = Field(..., description="ID unik response")
    object: str = Field(default="chat.completion")
    created: int = Field(..., description="Unix timestamp")
    model: str
    choices: List[ChatCompletionChoice]
    usage: UsageInfo
    metadata: Optional[MetadataResponse] = None


class ChatCompletionStreamChunk(BaseModel):
    """Chunk untuk streaming response"""
    id: str
    object: str = Field(default="chat.completion.chunk")
    created: int
    model: str
    choices: List[Dict[str, Any]]  # Delta content