# TASK-07 — Provider Adapter: OpenAI

| Item | Nilai |
|---|---|
| Milestone | M2 Provider Remote |
| Prioritas | P0 |
| Estimasi | 0.5 hari |
| Dependensi | TASK-06 |
| Referensi PRD | §8.5, F5 |

## Tujuan
Adapter OpenAI untuk chat, stream, dan embeddings. Karena format API gateway = format OpenAI, adapter ini paling tipis dan menjadi acuan. Kelas ini juga menjadi **kelas dasar `LocalRuntimeProvider`** (TASK-10), karena Local Runtime berbicara format OpenAI. Pembuatan payload, parsing chunk, dan mapping error harus dapat di-override (method terpisah, bukan inline).

## Spesifikasi
- File: `app/services/providers/openai_provider.py`, `code = "openai"`.
- Gunakan SDK `openai.AsyncOpenAI(api_key=..., base_url=cfg.base_url or default, http_client=shared_httpx, max_retries=0)` — retry ditangani gateway (fallback), bukan SDK.
- `chat()` → `client.chat.completions.create(**payload)`; payload dibangun dari `UnifiedChatRequest` hanya untuk field yang tidak `None`, ditambah `provider_options` (merge dangkal).
- `chat_stream()` → `stream=True, stream_options={"include_usage": True}`; map setiap chunk:
  - `choices[0].delta.content` → `delta_content`
  - `choices[0].delta.tool_calls` → `delta_tool_calls` (index, id, function.name, function.arguments)
  - chunk terakhir dengan `usage` → `UnifiedChunk(usage=...)`
  - `prompt_tokens_details.cached_tokens` → `cached_tokens`
- `embed()` → `client.embeddings.create(model, input, dimensions?)`.
- `health()` → `client.models.list()` dengan timeout 5 detik.
- Parameter khusus model reasoning (mis. `max_completion_tokens`, `reasoning_effort`) **tidak** diinterpretasi gateway; caller mengirim via `provider_options` atau field yang diteruskan apa adanya. Bila `models.config.max_tokens_param = "max_completion_tokens"`, adapter memetakan `max_tokens` ke nama itu.

### Mapping error
| SDK exception | Gateway |
|---|---|
| `APITimeoutError` | `UpstreamTimeout` |
| `APIConnectionError` | `UpstreamError` (retryable) |
| `RateLimitError` | `UpstreamRateLimited` |
| `InternalServerError` / status ≥ 500 | `UpstreamError` |
| `BadRequestError`, `UnprocessableEntityError` | `UpstreamBadRequest` (tidak fallback; pesan upstream diteruskan) |
| `AuthenticationError`, `PermissionDeniedError` | `UpstreamError` + log ERROR "provider key invalid" (fallback ke kandidat lain) |
| `NotFoundError` | `UpstreamError` + log ERROR "upstream model not found" |

## Deliverables
- [ ] `openai_provider.py`
- [ ] `tests/unit/providers/test_openai_provider.py` (mock HTTP dengan `respx`)

## Acceptance Criteria
1. Chat non-stream, stream, tool calling, JSON mode, image input berhasil terhadap API asli (smoke test manual dengan key nyata, dicatat di PR).
2. Usage stream terisi dari chunk akhir.
3. Seluruh mapping error di tabel teruji dengan respx.
4. Field `None` tidak muncul di payload yang terkirim (diverifikasi di test).
