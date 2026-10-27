# TASK-06 — Provider Abstraction, Registry & Streaming Util

| Item | Nilai |
|---|---|
| Milestone | M2 Provider Remote |
| Prioritas | P0 |
| Estimasi | 1.5 hari |
| Dependensi | TASK-02, TASK-04 |
| Referensi PRD | §7.2, §8.2, §8.3, F5 |

## Tujuan
Mendefinisikan kontrak tunggal untuk semua provider, schema unified internal, registry yang memuat provider/model/route dari DB, dan utilitas SSE.

## Spesifikasi

### Schema unified (`app/schemas/unified.py`)
```python
class UnifiedMessage(BaseModel):
    role: Literal["system","user","assistant","tool"]
    content: str | list[ContentPart] | None      # ContentPart: text | image_url
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

class UnifiedChatRequest(BaseModel):
    messages: list[UnifiedMessage]
    tools: list[ToolDef] | None = None
    tool_choice: str | dict | None = None
    response_format: dict | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    stream: bool = False
    provider_options: dict = {}        # passthrough mentah
    user: str | None = None

class Usage(BaseModel):
    prompt_tokens: int = 0; completion_tokens: int = 0; cached_tokens: int = 0; estimated: bool = False

class RuntimeMeta(BaseModel):          # diisi hanya oleh provider lokal (dari x_runtime)
    device: Literal["gpu","npu","cpu"]; backend: str
    load_ms: int = 0; queue_ms: int = 0; infer_ms: int | None = None
    warnings: list[str] = []

class UnifiedChatResponse(BaseModel):
    content: str | None; tool_calls: list[ToolCall] | None
    finish_reason: str | None; usage: Usage; upstream_model: str; raw_id: str | None
    reasoning_content: str | None = None
    runtime_meta: RuntimeMeta | None = None

class UnifiedChunk(BaseModel):
    delta_content: str | None = None
    delta_tool_calls: list[ToolCallDelta] | None = None   # index, id, name, arguments fragment
    finish_reason: str | None = None
    usage: Usage | None = None                            # hanya di chunk terakhir
    runtime_meta: RuntimeMeta | None = None               # hanya di chunk terakhir (lokal)

class UnifiedCompletionRequest(BaseModel):
    prompt: str; suffix: str | None = None                # suffix → FIM
    max_tokens: int | None = None; temperature: float | None = None; top_p: float | None = None
    stop: list[str] | None = None; seed: int | None = None; stream: bool = False
    provider_options: dict = {}

class UnifiedImageRequest(BaseModel):
    prompt: str; negative_prompt: str | None = None
    n: int = 1; size: str = "512x512"
    steps: int | None = None; guidance_scale: float | None = None; seed: int | None = None
    provider_options: dict = {}

class UnifiedImage(BaseModel):
    png_bytes: bytes; sha256: str; width: int; height: int
    seed: int; steps: int; guidance_scale: float

class UnifiedImageResponse(BaseModel):
    images: list[UnifiedImage]; runtime_meta: RuntimeMeta | None = None
```
Semua parameter `None` **tidak** dikirim ke provider (gateway tidak menyuntikkan default behavior), kecuali yang wajib provider (mis. `max_tokens` Anthropic).

### `app/services/providers/base.py`
```python
class BaseProvider(ABC):
    code: ClassVar[str]
    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient, settings: Settings): ...
    async def startup(self) -> None: ...                 # opsional (load model lokal)
    async def shutdown(self) -> None: ...
    async def health(self) -> ProviderHealth: ...
    @abstractmethod
    async def chat(self, model: ModelConfig, req: UnifiedChatRequest) -> UnifiedChatResponse: ...
    @abstractmethod
    def chat_stream(self, model: ModelConfig, req: UnifiedChatRequest) -> AsyncIterator[UnifiedChunk]: ...
    async def completion(self, model, req: UnifiedCompletionRequest) -> ...: raise CapabilityNotSupported
    def completion_stream(self, model, req) -> AsyncIterator[UnifiedChunk]: raise CapabilityNotSupported
    async def embed(self, model, inputs: list[str], dimensions: int | None,
                    provider_options: dict) -> UnifiedEmbeddingResponse:
        raise CapabilityNotSupported
    async def generate_images(self, model, req: UnifiedImageRequest) -> UnifiedImageResponse:
        raise CapabilityNotSupported
```
- Setiap provider punya `asyncio.Semaphore(max_concurrency)`.
- Wajib memetakan error native → `UpstreamTimeout`, `UpstreamRateLimited`, `UpstreamError`, `UpstreamBadRequest` (PRD §8.1 langkah 7).

### Registry (`app/core/registry.py`)
- `ProviderRegistry`: map `code → BaseProvider` untuk provider `is_enabled`. Kelas dipilih dari mapping `{"openai": OpenAIProvider, "anthropic": AnthropicProvider, "gemini": GeminiProvider, "llamacpp": LocalRuntimeProvider, "openvino": LocalRuntimeProvider}`. `LocalRuntimeProvider` diimplementasikan di TASK-10.
- `ModelConfig` memuat juga `device`, `runtime_backend`, `is_pinned`, `vram_mb`, `supports_fim`, `cost_per_image` agar router dan usage dapat membacanya tanpa query DB.
- `ModelCatalog`: cache in-memory `alias → ModelConfig` dan `route_alias → RouteConfig(targets terurut)`; dimuat saat startup dan via `reload()` (dipanggil Admin API setelah perubahan).
- Provider remote tanpa API key di `.env` → otomatis disabled dengan log WARNING (bukan crash).

### Streaming util (`app/utils/streaming.py`)
```python
def sse_event(data: dict | str) -> bytes     # b"data: {...}\n\n" (orjson)
SSE_DONE = b"data: [DONE]\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

async def guarded_stream(source: AsyncIterator[bytes], request: Request,
                         on_finish: Callable[[StreamOutcome], Awaitable[None]]) -> AsyncIterator[bytes]:
    """Yield bytes; deteksi disconnect; tangkap CancelledError/GeneratorExit;
       panggil on_finish(status=success|error|cancelled, usage, ttft_ms) TEPAT SEKALI di finally."""
```
- `on_finish` dijalankan dengan `asyncio.shield` / task terpisah agar pencatatan tetap selesai meski client putus.
- Heartbeat komentar `: ping\n\n` setiap 15 detik jika tidak ada chunk (mencegah timeout proxy) — dapat dimatikan via settings.

### Parser SSE upstream
- `aiter_sse(response: httpx.Response) -> AsyncIterator[tuple[event, data]]` generik untuk OpenAI/llama/Gemini; Anthropic memakai SDK resminya atau parser yang sama dengan nama event.

## Deliverables
- [ ] `app/schemas/unified.py`
- [ ] `app/services/providers/base.py`
- [ ] `app/core/registry.py`
- [ ] `app/utils/streaming.py`
- [ ] Fake provider untuk test (`tests/fakes/fake_provider.py`) yang bisa disetel sukses/gagal/lambat

## Acceptance Criteria
1. Registry memuat provider & model dari DB; `reload()` merefleksikan perubahan tanpa restart.
2. `guarded_stream` dengan fake provider: `on_finish` terpanggil tepat 1x untuk skenario sukses, error di tengah, dan client disconnect.
3. Provider tanpa API key ter-skip dengan WARNING.
4. Unit test parser SSE untuk event multi-baris dan keep-alive.
