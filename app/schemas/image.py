from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class ImageGenerationRequest(BaseModel):
    """Request untuk generate gambar"""
    model: str = Field(
        default="stable-diffusion-v1-5",
        description="Model image generation"
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Prompt untuk generate gambar"
    )
    negative_prompt: Optional[str] = Field(
        None,
        max_length=1000,
        description="Negative prompt (hal yang tidak diinginkan)"
    )
    width: Optional[int] = Field(
        512,
        ge=256,
        le=1024,
        multiple_of=8,
        description="Lebar gambar (pixel, kelipatan 8; SD 1.5 optimal 512)"
    )
    height: Optional[int] = Field(
        512,
        ge=256,
        le=1024,
        multiple_of=8,
        description="Tinggi gambar (pixel)"
    )
    steps: Optional[int] = Field(
        20,
        ge=1,
        le=150,
        description="Jumlah inference steps"
    )
    cfg_scale: Optional[float] = Field(
        7.5,
        ge=1.0,
        le=30.0,
        description="Classifier-free guidance scale"
    )
    seed: Optional[int] = Field(
        None,
        ge=-1,
        description="Seed untuk reproducibility (-1 = random)"
    )
    num_images: Optional[int] = Field(
        1,
        ge=1,
        le=4,
        description="Jumlah gambar yang di-generate"
    )
    output_format: Optional[Literal["png", "jpeg", "webp"]] = Field(
        "png",
        description="Format output gambar"
    )

    @field_validator('prompt')
    @classmethod
    def validate_prompt(cls, v):
        if not v.strip():
            raise ValueError('Prompt tidak boleh kosong')
        return v.strip()


class ImageData(BaseModel):
    """Data gambar yang di-generate"""
    url: str = Field(..., description="URL publik gambar")
    revised_prompt: Optional[str] = Field(
        None,
        description="Prompt yang direvisi (jika ada)"
    )
    seed: Optional[int] = Field(None, description="Seed yang dipakai")


class ImageGenerationResponse(BaseModel):
    """Response image generation"""
    created: int = Field(..., description="Unix timestamp")
    model: str
    data: List[ImageData]
    metadata: Optional[dict] = None