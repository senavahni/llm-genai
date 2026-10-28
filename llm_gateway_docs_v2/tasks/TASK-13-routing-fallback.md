# TASK-13 — Service: Router, Fallback & Eksekusi Chat

| Item | Nilai |
|---|---|
| Milestone | M4 Core API |
| Prioritas | P0 |
| Estimasi | 2 hari |
| Dependensi | TASK-06 s.d. TASK-08, TASK-10 |
| Referensi PRD | §8.1–§8.4, §9.5, F6, G3 |

## Tujuan
Menerjemahkan `model` yang diminta caller menjadi daftar kandidat, mengeksekusi dengan fallback yang aman, dan menghasilkan data attempt untuk pencatatan.

## Spesifikasi

### `app/services/router_service.py`
```python
async def resolve(requested: str, auth: AuthContext, need: Capabilities) -> list[ModelConfig]:
```
1. Jika `requested` adalah alias route → ambil targets enabled; urutkan:
   - `priority`: `priority ASC`
   - `round_robin`: rotasi berbobot (counter in-memory per route), lalu sisanya sebagai fallback.
2. Jika alias model langsung → `[model]`.
3. Jika tidak ditemukan → `ModelNotFound`.
4. Filter izin: setiap kandidat (dan alias yang diminta) harus cocok dengan salah satu `project_allowed_models.model_pattern` (glob). Tidak ada pola → default tolak semua (project harus dikonfigurasi). Semua terfilter → `ModelNotAllowed`.
5. Filter kapabilitas (`need.tools`, `need.vision`, `need.json`, `need.stream`, `model_type`): kandidat yang tidak mendukung dibuang; bila semuanya terbuang → `CapabilityNotSupported` dengan pesan kapabilitas apa yang kurang.
6. Buang kandidat yang provider-nya disabled / tidak ada di registry.
7. Circuit breaker sederhana per model: ≥ 5 error retryable dalam 60 detik → kandidat dipindah ke akhir daftar selama 30 detik (tidak dibuang).
8. **Preferensi model lokal yang sudah termuat (opsional, `routing.prefer_loaded=true` per route):** untuk route dengan beberapa kandidat lokal ber-priority sama, kandidat yang sedang termuat di runtime (dari cache `/runtime/status`, TTL 5 detik) diutamakan. Tujuannya menghindari swap 7B yang tidak perlu. Urutan priority berbeda tetap dihormati.

`Capabilities` diturunkan dari request:

| Kapabilitas | Sumber | Kolom model |
|---|---|---|
| tools | `tools` tidak kosong | `supports_tools` |
| vision | ada content part `image_url` | `supports_vision` |
| json | `response_format` | `supports_json_mode` |
| stream | `stream=true` | `supports_streaming` |
| fim | `/v1/completions` dengan `suffix` | `supports_fim` |
| tipe | endpoint | `model_type` ∈ chat / completion / embedding / image |

Contoh: `model="code"` + `tools` → Coder-7B lolos, `local/qwen2.5-7b` lolos, remote kode lolos. `model="autocomplete"` + `suffix` → hanya Coder-1.5B.

### Fallback untuk model lokal
- Error runtime `model_busy`, `device_oom`, `device_unavailable` bersifat **retryable**. Contoh: `smart` → Claude gagal → GPT gagal → `local/qwen2.5-7b` sibuk → 502 dengan semua attempt tercatat. Contoh lain: `code` → Coder-7B sibuk (GPU sedang dipakai model heavy lain) → fallback ke remote.
- Timeout chunk pertama:
  - provider remote: `first_token_timeout` = 60 detik;
  - provider lokal: `LOCAL_FIRST_TOKEN_TIMEOUT_S` = 120 detik, karena mencakup waktu antrean + swap model.
- Attempt menyimpan `device` dan `runtime_meta` (load_ms, queue_ms) untuk dicatat TASK-15.

### Service lain yang memakai router yang sama
- `completion_service.execute[_stream]` (raw + FIM)
- `embedding_service.execute` (tanpa stream)
- `image_service.execute` (TASK-14), fallback hanya bila belum ada gambar yang dihasilkan.

Semua memakai helper generik `run_with_fallback(candidates, call_fn)` agar logika attempt seragam.

### `app/services/chat_service.py`
```python
async def execute(ctx: RequestCtx, req: UnifiedChatRequest, candidates: list[ModelConfig]) -> ChatResult
async def execute_stream(ctx, req, candidates) -> AsyncIterator[UnifiedChunk]
```
**Non-stream:**
```
for i, model in enumerate(candidates, 1):
    t0 = now
    try:
        resp = await asyncio.wait_for(provider.chat(model, req), timeout=provider.timeout)
        ctx.attempts.append(Attempt(i, model, "success", latency))
        return ChatResult(resp, model, ctx.attempts)
    except GatewayError as e:
        ctx.attempts.append(Attempt(i, model, "error", e.code, latency))
        if not e.retryable: raise
raise UpstreamError("All candidates failed", attempts=...)
```
**Stream:**
- Buka stream kandidat; tunggu **chunk pertama** (`anext`) dengan timeout `first_token_timeout` (default 60 detik, remote) — jika gagal & retryable → kandidat berikutnya.
- Setelah chunk pertama keluar ke caller → **tidak ada fallback**; error berikutnya diteruskan sebagai event error dan attempt ditandai `error`.
- Kumpulkan teks & tool_calls (untuk payload log bila diaktifkan) dan usage akhir.

### Validasi request
- `max_tokens` > `models.max_output_tokens` → dipotong ke batas model dan header `X-Gateway-Warning: max_tokens_clamped` (tidak error).
- `messages` kosong → 400.

> **Catatan 28 Okt 2026:** katalog kini 8 route (route `reason` dihapus bersama DeepSeek/Phi,
> `embed-default` hanya remote). AC8 diuji untuk 8 route tersebut. Opsi `prefer_loaded` disimpan di
> kolom baru `model_routes.config` (migrasi 0003). Kapabilitas `image_edit` (image-to-image) =
> `"image-to-image" ∈ models.config.tasks`.

## Deliverables
- [x] `router_service.py` dengan circuit breaker, round robin berbobot, `prefer_loaded`,
      `run_with_fallback` & `open_stream` generik (dipakai chat/completion/embedding/image)
- [x] `chat_service.py` (non-stream & stream), `context.py` (`RequestCtx`, `Attempt`, `Outcome`)
- [x] `AuthContext.allowed_models` dari `project_allowed_models` (key admin tanpa project = `*`)
- [x] Unit test menggunakan fake provider (`tests/unit/test_router.py`, 26 test): urutan priority,
      round robin, izin glob, kapabilitas, fallback sebelum token pertama, tidak fallback setelah
      token pertama, timeout chunk pertama, error non-retryable langsung gagal, circuit breaker

## Acceptance Criteria
1. Route `smart` dengan kandidat-1 fake 503 → respons sukses dari kandidat-2; attempts = 2.
2. Kandidat-1 mengembalikan 400 → langsung 400, tidak mencoba kandidat-2.
3. Stream yang putus setelah token pertama tidak memicu kandidat lain.
4. Project dengan pola `local/*` tidak bisa memakai `smart` (403 `model_not_allowed`).
5. Request dengan `tools` ke route yang hanya berisi model tanpa tools → 400 `capability_not_supported`.
6. Fake runtime mengembalikan `model_busy` untuk Coder-7B → route `code` fallback ke kandidat berikutnya; attempt pertama tercatat `error_type=model_busy`, `device=gpu`.
7. `vision` dengan gambar → hanya kandidat `supports_vision`; `autocomplete` dengan `suffix` → hanya kandidat `supports_fim`.
8. Kesembilan route default PRD §9.5 ter-resolve sesuai urutan yang diharapkan (test tabel).
