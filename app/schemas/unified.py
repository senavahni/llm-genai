"""Schema internal (unified) yang dipakai semua provider adapter.

Aturan: field bernilai None TIDAK dikirim ke provider. Gateway tidak menyuntikkan default behavior
selain yang diwajibkan provider (mis. max_tokens Anthropic)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ------------------------------------------------------------------ message
class ImageURL(_Model):
    url: str  # data URL base64 atau http(s)
    detail: str | None = None


class TextPart(_Model):
    type: Literal["text"] = "text"
    text: str


class ImagePart(_Model):
    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


ContentPart = TextPart | ImagePart


class FunctionCall(_Model):
    name: str
    arguments: str = ""  # string JSON (format OpenAI)


class ToolCall(_Model):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class FunctionDef(_Model):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ToolDef(_Model):
    type: Literal["function"] = "function"
    function: FunctionDef


class UnifiedMessage(_Model):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def text(self) -> str:
        """Gabungan seluruh bagian teks (bagian gambar diabaikan)."""
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        return "".join(p.text for p in self.content if isinstance(p, TextPart))


# ------------------------------------------------------------------ request
class UnifiedChatRequest(_Model):
    messages: list[UnifiedMessage]
    tools: list[ToolDef] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    stream: bool = False
    provider_options: dict[str, Any] = Field(default_factory=dict)  # passthrough mentah
    user: str | None = None


class UnifiedCompletionRequest(_Model):
    prompt: str
    suffix: str | None = None  # suffix → FIM
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    seed: int | None = None
    stream: bool = False
    provider_options: dict[str, Any] = Field(default_factory=dict)


class UnifiedImageRequest(_Model):
    prompt: str
    negative_prompt: str | None = None
    n: int = 1
    size: str = "512x512"
    steps: int | None = None
    guidance_scale: float | None = None
    seed: int | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------ response
class Usage(_Model):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class RuntimeMeta(_Model):
    """Diisi hanya oleh provider lokal (dari field x_runtime respons Local Runtime)."""

    device: Literal["gpu", "npu", "cpu"]
    backend: str
    load_ms: int = 0
    queue_ms: int = 0
    infer_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)


class UnifiedChatResponse(_Model):
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    upstream_model: str
    raw_id: str | None = None
    reasoning_content: str | None = None
    runtime_meta: RuntimeMeta | None = None


class ToolCallDelta(_Model):
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None  # fragmen string JSON


class UnifiedChunk(_Model):
    delta_content: str | None = None
    delta_reasoning: str | None = None
    delta_tool_calls: list[ToolCallDelta] | None = None
    finish_reason: str | None = None
    usage: Usage | None = None  # hanya di chunk terakhir
    runtime_meta: RuntimeMeta | None = None  # hanya di chunk terakhir (lokal)
    upstream_model: str | None = None
    raw_id: str | None = None


class UnifiedCompletionResponse(_Model):
    text: str
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    upstream_model: str
    raw_id: str | None = None
    runtime_meta: RuntimeMeta | None = None


class UnifiedEmbeddingResponse(_Model):
    vectors: list[list[float]]
    usage: Usage = Field(default_factory=Usage)
    upstream_model: str
    runtime_meta: RuntimeMeta | None = None


class UnifiedImage(_Model):
    png_bytes: bytes
    sha256: str
    width: int
    height: int
    seed: int
    steps: int
    guidance_scale: float


class UnifiedImageResponse(_Model):
    images: list[UnifiedImage]
    upstream_model: str | None = None
    runtime_meta: RuntimeMeta | None = None


# ------------------------------------------------------------------ health
class ProviderHealth(_Model):
    ok: bool
    latency_ms: int | None = None
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
