# TASK-15 — Service: Usage, Cost Accounting & Request Log

| Item | Nilai |
|---|---|
| Milestone | M4 Core API |
| Prioritas | P0 |
| Estimasi | 1.5 hari |
| Dependensi | TASK-04, TASK-13 |
| Referensi PRD | §9.2, §9.3, F10–F12, G4, NF4 |

## Tujuan
Menjamin setiap request tercatat lengkap & konsisten (accountable): baris `requests`, `request_attempts`, payload opsional, dan agregat `usage_daily`.

## Spesifikasi

### `app/services/usage_service.py`
**`start(ctx)`** — dipanggil setelah resolve model, sebelum memanggil provider:
- `INSERT INTO requests (id, project_id, api_key_id, endpoint, requested_model, is_stream, status='pending', client_ip, user_agent, caller_task, caller_agent, tags, created_at)`.
- Bila DB tidak tersedia → raise `ServiceUnavailable` (503). Prinsip: **tidak ada pemakaian tanpa pencatatan**.

**`finish(ctx, outcome)`** — background task / `on_finish` stream; satu transaksi:
1. `UPDATE requests SET status, http_status, error_type, error_message (dipotong 2000 char), finish_reason, resolved_model_id, provider_code, upstream_model, prompt/completion/total/cached_tokens, **image_count, device, load_ms, queue_ms** (dari `runtime_meta`), cost_usd, latency_ms, ttft_ms, attempts, completed_at, tags = tags || {"usage_estimated": ...}`.
2. `INSERT request_attempts` (bulk) untuk semua attempt, termasuk kolom `device`.
3. Upsert `usage_daily` (PRD §9.3) dengan `day = (created_at AT TIME ZONE 'UTC')::date`, `model_alias` = alias model yang **benar-benar melayani** (bukan route), `provider_code`, dan akumulasi `image_count`. Request gagal total dicatat dengan `model_alias = requested_model`, `provider_code='none'`.
4. Jika `auth.log_payloads` → `INSERT request_payloads (request_body, response_body, expires_at = now + retention)`. Hapus field gambar base64 > 100 KB dari payload (diganti placeholder `"<image omitted: N bytes>"`).
- Retry penulisan DB 3x (backoff 0.2/0.5/1 detik); jika tetap gagal → tulis record JSON ke `logs/usage_fallback.jsonl` agar bisa di-replay (`manage.py replay-usage`).

**Biaya:** `cost = prompt_tokens × input_cost_per_mtok / 1e6 + completion_tokens × output_cost_per_mtok / 1e6 + image_count × cost_per_image` dengan `Decimal`. Model lokal default biaya 0, tetapi boleh diisi estimasi biaya listrik/amortisasi agar laporan biaya per project tetap bermakna. `cached_tokens` memakai `models.config.cached_input_cost_per_mtok` bila ada.

### Akuntabilitas device (model lokal)
- `requests.device` diisi dari `runtime_meta.device` yang **dilaporkan runtime**, bukan dari konfigurasi. Inilah bukti NF9 (tidak ada inferensi CPU).
- Bila provider lokal sukses tetapi `runtime_meta` tidak ada → `device=NULL` dan `tags.runtime_meta_missing=true`, lalu log WARNING (harus 0 di test).
- `load_ms > 0` menandakan request ini memicu swap model; dipakai metrik `swap_triggered_by_request` dan analisis thrashing.
- Korelasi: `runtime_events.request_id` = `requests.id` untuk event load/evict yang dipicu request.

### Gambar
- `generated_images` ditulis oleh `image_service.store()` (TASK-14) dalam transaksi terpisah setelah file tersimpan. Bila insert gagal, file dihapus agar tidak ada file yatim.
- Untuk `response_format=b64_json`, tidak ada baris `generated_images`; yang tercatat hanya `image_count` dan metadata di `tags` (`seeds`, `steps`, `size`).

### Sweeper orphan
- Task periodik di lifespan (setiap 5 menit): `UPDATE requests SET status='error', error_type='orphaned' WHERE status='pending' AND created_at < now() - interval '10 minutes'`.
- Hitung juga ke `usage_daily` sebagai error.

### Konsistensi
- Query verifikasi (dipakai di test & endpoint admin `GET /admin/usage/verify?day=`):
```sql
SELECT r.project_id, count(*) AS req_rows, COALESCE(sum(u.request_count),0) AS agg_rows ...
```
selisih harus 0.

## Deliverables
- [ ] `usage_service.py` (`start`, `finish`, `finish_stream` factory)
- [ ] Sweeper di `lifespan.py`
- [ ] `manage.py replay-usage`
- [ ] Endpoint verifikasi konsistensi
- [ ] Test integrasi dengan DB nyata (database test terpisah `llm_gateway_test`)

## Acceptance Criteria
1. 100 request campuran (sukses, fallback, gagal, stream cancel) → semua `requests` berstatus final, `request_attempts` sesuai jumlah percobaan.
2. Jumlah `usage_daily.request_count` = jumlah baris `requests` per hari/project (selisih 0).
3. Biaya terhitung benar untuk harga contoh (unit test `Decimal`, tanpa float error).
4. Matikan PostgreSQL saat request berjalan → request baru 503; `finish` yang gagal tertulis ke `usage_fallback.jsonl` dan bisa di-replay.
5. Payload hanya tersimpan untuk project dengan `log_payloads=true`.
6. Request lokal selalu memiliki `device ∈ {gpu, npu}`; request yang memicu swap memiliki `load_ms > 0` dan baris `runtime_events` dengan `request_id` sama.
7. `usage_daily.image_count` = Σ `requests.image_count` per hari/project.
