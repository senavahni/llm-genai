"""Schema request publik kompatibel OpenAI (TASK-14). Field tak dikenal dikumpulkan ke
`provider_options` (passthrough), termasuk `provider_options` eksplisit dari `extra_body`."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_METADATA_KEYS = 16


class OpenAIRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=128)
    user: str | None = None
    metadata: dict[str, str] | None = None

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and len(v) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata maksimal {MAX_METADATA_KEYS} key")
        return v

    def provider_options(self) -> dict[str, Any]:
        """Field tak dikenal (mis. top_k) + `provider_options` eksplisit → passthrough."""
        extra = dict(self.model_extra or {})
        explicit = extra.pop("provider_options", None)
        if isinstance(explicit, dict):
            extra.update(explicit)
        return extra


class ChatCompletionRequest(OpenAIRequest):
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stop: str | list[str] | None = None
    seed: int | None = None
    n: int | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None

    @property
    def include_usage(self) -> bool:
        return bool((self.stream_options or {}).get("include_usage"))


class CompletionRequest(OpenAIRequest):
    prompt: str | list[str]
    suffix: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stop: str | list[str] | None = None
    seed: int | None = None
    n: int | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    echo: bool = False

    @property
    def include_usage(self) -> bool:
        return bool((self.stream_options or {}).get("include_usage"))


class EmbeddingRequest(OpenAIRequest):
    input: str | list[str] | list[int] | list[list[int]]
    dimensions: int | None = Field(default=None, ge=1)
    encoding_format: Literal["float", "base64"] = "float"
