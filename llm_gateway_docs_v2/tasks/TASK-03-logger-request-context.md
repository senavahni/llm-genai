# TASK-03 — Utils: Logger, Request Context, Helper

| Item | Nilai |
|---|---|
| Milestone | M1 Fondasi |
| Prioritas | P0 |
| Estimasi | 1 hari |
| Dependensi | TASK-02 |
| Referensi PRD | §12, NF1, NF5 |

## Tujuan
Logging terstruktur JSON yang non-blocking, ter-rotasi, berisi context per request, dan otomatis meredaksi secret.

## Spesifikasi

### `app/utils/logger.py`
- `setup_logging(settings, component: Literal["gateway","runtime"] = "gateway")`:
  - Handler file via `QueueHandler` → `QueueListener` (thread) agar penulisan file tidak memblokir event loop.
  - Gateway: `logs/app.log` (≥ `LOG_LEVEL`), `logs/error.log` (≥ ERROR), `logs/access.log` (logger `gateway.access`, `propagate=False`).
  - Runtime: `logs/runtime.log`, `logs/runtime-error.log`. Log native llama.cpp/OpenVINO yang ditangkap ditulis lewat logger `runtime.native` level DEBUG.
  - `TimedRotatingFileHandler(when="midnight", backupCount=14|30, encoding="utf-8", utc=True)`.
  - Console: `ConsoleRenderer` berwarna bila `app_env=dev`, JSON bila `prod`.
  - Atur ulang logger `uvicorn`, `uvicorn.error`, `uvicorn.access` (matikan access log bawaan uvicorn; diganti access log sendiri).
- Processor structlog berurutan: `merge_contextvars` → `add_log_level` → `TimeStamper(fmt="iso", utc=True)` → `redact_processor` → `format_exc_info` → renderer (`orjson`).
- `get_logger(name) -> BoundLogger`.

### Redaksi (`redact_processor`)
- Kunci sensitif (case-insensitive): `authorization`, `x-api-key`, `x-runtime-token`, `runtime_token`, `api_key`, `password`, `secret`, `token`, `key_hash`.
- Pola nilai: `sk-[A-Za-z0-9_\-]{10,}`, `sk-ant-[A-Za-z0-9_\-]+`, `AIza[0-9A-Za-z_\-]{20,}`, `lgw_[A-Za-z0-9]{8}_[A-Za-z0-9_\-]+` → ganti `***REDACTED***` (prefix `lgw_xxxxxxxx` boleh tersisa).
- Rekursif ke dict/list.

### `app/middlewares/request_context.py` (pure ASGI middleware, bukan `BaseHTTPMiddleware`, agar streaming tidak terganggu)
- Ambil `X-Request-ID` dari header jika UUID valid; jika tidak, buat `uuid7`/`uuid4`.
- `structlog.contextvars.bind_contextvars(request_id=..., client_ip=..., path=...)`.
- Simpan di `scope["state"]["request_id"]`.
- Tambahkan header respons `X-Request-ID`.
- Setelah respons selesai (termasuk akhir stream), tulis satu baris ke `gateway.access`:
  `method, path, status, latency_ms, request_id, project_slug, key_prefix, bytes_sent, user_agent`.
- Selalu `clear_contextvars()` di akhir.

### `app/utils/helper.py`
- `new_request_id() -> uuid.UUID`
- `utcnow() -> datetime` (aware UTC)
- `calc_cost(prompt_tokens, completion_tokens, in_per_mtok, out_per_mtok) -> Decimal` (pakai `Decimal`, pembulatan 8 digit)
- `glob_match(pattern, value) -> bool` (`fnmatch.fnmatchcase`)
- `estimate_tokens(text_or_messages) -> int` (heuristik `len(chars)/4`, dipakai hanya jika provider tidak memberi usage)
- `client_ip(scope, trust_proxy: bool) -> str`

## Deliverables
- [ ] `app/utils/logger.py`, `app/utils/helper.py`
- [ ] `app/middlewares/request_context.py`
- [ ] `tests/unit/test_logger_redaction.py`, `tests/unit/test_helper.py`

## Acceptance Criteria
1. Setiap request menghasilkan tepat 1 baris di `access.log` dengan `request_id` yang sama dengan header respons.
2. Log yang mengandung `Authorization: Bearer lgw_ab12cd34_secret` tertulis sebagai `lgw_ab12cd34_***REDACTED***` atau `***REDACTED***`.
3. Uji beban 200 request bersamaan tidak memperlihatkan peningkatan latency signifikan akibat logging (QueueHandler bekerja).
4. File log berputar saat pergantian hari (uji dengan mock waktu atau `when="S"` di test).
