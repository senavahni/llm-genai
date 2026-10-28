"""Schema endpoint gambar publik (TASK-14), kompatibel OpenAI + ekstensi model lokal."""

from typing import Literal

from pydantic import Field

from app.schemas.openai_compat import OpenAIRequest


class ImageGenerationRequest(OpenAIRequest):
    model: str = Field(default="image", min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=1000)
    n: int = Field(default=1, ge=1, le=4)
    size: str = "512x512"
    response_format: Literal["b64_json", "url"] = "url"
    # ekstensi gateway (boleh top-level atau extra_body)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    steps: int | None = Field(default=None, ge=1)
    guidance_scale: float | None = None
    seed: int | None = Field(default=None, ge=0)


class ImageEditRequest(ImageGenerationRequest):
    """`/v1/images/edits` (image-to-image), dibangun dari form multipart OpenAI."""

    image: bytes
    strength: float | None = Field(default=None, gt=0, le=1)
