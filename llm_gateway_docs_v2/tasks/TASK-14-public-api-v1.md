# TASK-14 — Public API v1: Schema, Controller, Route

| Item | Nilai |
|---|---|
| Milestone | M4 Core API |
| Prioritas | P0 |
| Estimasi | 3 hari |
| Dependensi | TASK-05, TASK-13, TASK-15 (dikerjakan paralel; hook usage), TASK-11, TASK-12 |
| Referensi PRD | §8.3, §8.4, §10.2, F1–F4, F3b, F16 |

## Tujuan
Menyediakan endpoint OpenAI-compatible yang dipakai project lain, dengan pemisahan tegas routes → controllers → services.

## Spesifikasi

### Schema (`app/schemas/openai_compat.py`)
- `ChatCompletionRequest`: field OpenAI umum (`model`, `messages`, `tools`, `tool_choice`, `response_format`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop` (str|list), `seed`, `n` (hanya 1 → selain itu 400), `stream`, `stream_options`, `user`, `metadata` (dict str→str, maks 16 key), `parallel_tool_calls`).
- `model_config = ConfigDict(extra="allow")` → field tak dikenal dikumpulkan ke `provider_options` (passthrough), termasuk `extra_body.provider_options` eksplisit.
- `ChatCompletionResponse`, `ChatCompletionChunk` sesuai format OpenAI (`id="chatcmpl-<request_id>"`, `object`, `created`, `model` = alias yang diminta caller, `choices`, `usage`, `system_fingerprint=null`).
- `CompletionRequest/Response` (legacy) dengan field **`suffix`** (FIM), `prompt` berupa string (list string → 400 di v1), `max_tokens`, `stop`, `stream`, `echo=false` saja.
- `EmbeddingRequest` (`input`: str | list[str] | list[int] | list[list[int]], `dimensions`, `encoding_format`: float|base64), `EmbeddingResponse`. Token-ID input hanya untuk model remote; model lokal → 400.
- **`app/schemas/images.py`**: `ImageGenerationRequest` (`model`, `prompt` ≤ 1000 char, `n` 1–4, `size` default `512x512`, `response_format` `b64_json`|`url`, `user`, plus ekstensi `negative_prompt`, `steps`, `guidance_scale`, `seed` — boleh di top-level atau `extra_body`). `ImageGenerationResponse` sesuai OpenAI: `{"created": ..., "data": [{"b64_json"|"url", "revised_prompt": null}]}` + ekstensi `x_meta` per gambar (`seed`, `steps`, `guidance_scale`, `width`, `height`).
- `ModelObject` (`id`, `object="model"`, `created`, `owned_by`=provider/“gateway-route”) + ekstensi `x_capabilities` (tools, vision, json, fim, image, embedding), `x_tier`, dan `x_device` (remote/gpu/npu).
- Converter `to_unified()` / `from_unified()` di modul terpisah (`app/schemas/converters.py`).

### Controllers
`app/controllers/chat_controller.py`
```python
async def create_chat_completion(body, auth, request) -> Response:
    ctx = RequestCtx.from_request(request, auth, endpoint="chat.completions", body=body)
    await ratelimit_service.check(auth, est_tokens)          # TASK-16
    await quota_service.check(auth.project_id)               # TASK-16
    candidates = await router_service.resolve(body.model, auth, caps(body))
    await usage_service.start(ctx)                           # TASK-15
    if body.stream:
        gen = chat_service.execute_stream(ctx, unified, candidates)
        return StreamingResponse(guarded_stream(encode_openai_chunks(gen, ctx), request,
                                 on_finish=usage_service.finish_stream(ctx)),
                                 media_type="text/event-stream", headers=SSE_HEADERS | ctx.headers())
    result = await chat_service.execute(ctx, unified, candidates)
    background.add_task(usage_service.finish, ctx, result)
    return ORJSONResponse(from_unified(result, body.model), headers=ctx.headers())
```
- Exception di jalur non-stream juga memanggil `usage_service.finish` dengan status `error` (try/except di controller lalu re-raise).
- Header gateway: `X-Request-ID`, `X-Gateway-Provider`, `X-Gateway-Model`, `X-Gateway-Device`, `X-Gateway-Attempts` (untuk stream dikirim di awal berdasarkan kandidat yang memberi chunk pertama — controller menunggu chunk pertama sebelum membuat `StreamingResponse`).
- `completion_controller.py`: raw dan FIM (`suffix` → kapabilitas `fim` di router), stream & non-stream.
- `embedding_controller.py`: batch input maks 2048 item; `encoding_format=base64` → float32 little-endian base64.
- `model_controller.py`: filter berdasarkan izin project.
- `usage_controller.py`: query `usage_daily` project sendiri, termasuk `image_count`.

`app/controllers/image_controller.py` + `app/services/image_service.py`:
```python
async def create_image(body, auth, request):
    ctx = RequestCtx.from_request(request, auth, endpoint="images.generations", body=body)
    await ratelimit_service.check(auth, est_tokens=0)
    await quota_service.check(auth.project_id, images=body.n)
    candidates = await router_service.resolve(body.model, auth, Capabilities(type="image"))
    validate_image_params(body, candidates)           # size ∈ allowed_sizes, steps ≤ max_steps
    await usage_service.start(ctx)
    result = await image_service.execute(ctx, to_unified(body), candidates)   # fallback via run_with_fallback
    if body.response_format == "url":
        saved = await image_service.store(ctx, result)  # tulis file + insert generated_images
    ...
```
- `image_service.store()` menulis PNG ke `STORAGE_DIR/images/{yyyy-mm-dd}/{request_id}_{idx}.png` lewat thread (`anyio.to_thread`), menghitung sha256, lalu insert `generated_images` (`expires_at = now + project.image_retention_days`). URL yang dikembalikan: `{public_base}/v1/images/files/{image_id}`. `public_base` diambil dari header `X-Forwarded-*` bila `TRUST_PROXY`, atau dari `request.base_url`.
- `GET /v1/images/files/{image_id}` (scope `images`): cek `project_id` = project pemanggil dan belum kedaluwarsa; jika tidak → 404 `image_not_found` (tidak membocorkan keberadaan). Kirim `FileResponse` dengan `Cache-Control: private, max-age=3600`. Path diambil dari DB dan di-resolve di dalam `STORAGE_DIR` (anti path traversal).
- Gambar tidak pernah ditulis ke `request_payloads` (hanya metadata: prompt, seed, steps).

### Routes (`app/routes/v1/*.py`)
```python
router = APIRouter(prefix="/v1", tags=["v1"])

@router.post("/chat/completions", dependencies=[Depends(require_scope("chat"))])
async def chat_completions(body: ChatCompletionRequest, request: Request,
                           auth: AuthContext = Depends(get_auth)):
    return await chat_controller.create_chat_completion(body, auth, request)
```
Route hanya memanggil controller — tidak ada logika bisnis.

### Caller tracing
- `X-Caller-Task`, `X-Caller-Agent` (maks 128 char) & `metadata` body → disimpan di `requests.caller_task`, `caller_agent`, `tags`.
- `metadata` **tidak** diteruskan ke provider kecuali caller menaruhnya di `provider_options`.

> **Catatan 28 Okt 2026:** ditambah `POST /v1/images/edits` (multipart format OpenAI →
> image-to-image SD lokal; `mask` → 400 `unsupported_parameter`). Rate limit & kuota (TASK-16)
> belum ada; titik hook ditandai di controller.

## Deliverables
- [x] `app/schemas/openai_compat.py`, `app/schemas/converters.py`
- [x] `app/schemas/images.py` (+ `ImageEditRequest`)
- [x] 6 controller (chat, completion, embedding, image, model, usage) + file route v1 (`chat.py`, `completions.py`, `embeddings.py`, `images.py`, `models.py`, `usage.py`); helper bersama `controllers/common.py` (SSE setelah chunk pertama, event error SSE, pencatatan error)
- [x] `app/services/image_service.py`, `app/services/completion_service.py`, `app/services/embedding_service.py`
- [x] Test integrasi dengan fake provider via `httpx.AsyncClient(transport=ASGITransport(app))` (`tests/integration/test_api_v1.py`)
- [x] Test kompatibilitas memakai SDK `openai` resmi terhadap app (lewat `httpx2.ASGITransport`, setara uvicorn tanpa port)

## Acceptance Criteria
1. Contoh kode PRD §10.2 berjalan tanpa modifikasi selain `base_url` & `api_key`.
2. Stream mengirim `data: [DONE]` di akhir; dengan `stream_options.include_usage=true` chunk usage muncul sebelum `[DONE]`.
3. `GET /v1/models` hanya menampilkan model/route yang diizinkan project.
4. `n=2` → 400 dengan pesan jelas.
5. Field tak dikenal (mis. `top_k`) diteruskan ke provider via `provider_options`.
6. Embedding `encoding_format=base64` dapat didekode oleh SDK OpenAI.
7. `client.images.generate(model="image", size="512x512")` menghasilkan PNG valid. `size="1024x1024"` → 400 `unsupported_size` dengan daftar ukuran yang tersedia.
8. `response_format="url"` → URL dapat diunduh dengan key project yang sama; key project lain → 404.
9. `/v1/completions` dengan `suffix` ke `autocomplete` mengembalikan potongan kode tengah. Konfigurasi autocomplete Continue berbasis completions dapat memakainya.
10. Chat `vision` dengan gambar base64 dan URL berhasil; header `X-Gateway-Device: gpu`.
