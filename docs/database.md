# Database

PostgreSQL portable (≥ 14; terpasang 18.x), database `llm_gateway`, schema `public`, migrasi
Alembic (`migrations/versions/0001`–`0003`, `scripts\migrate.bat`). Enum = `VARCHAR + CHECK`,
semua waktu `TIMESTAMPTZ` (UTC). Model ORM: `app/models/`.

## ERD

```
projects 1─* api_keys
projects 1─* quotas
projects 1─* project_allowed_models
projects 1─* requests *─1 api_keys
providers 1─* models
model_routes 1─* model_route_targets *─1 models
requests 1─* request_attempts
requests 1─0..1 request_payloads
requests 1─* generated_images
models   1─* runtime_events
usage_daily  (agregat: day × project × model_alias × provider)
audit_logs   (aksi admin)
```

## Tabel

### Tenant & akses
| Tabel | Isi | Kolom penting |
|---|---|---|
| `projects` | satu project/agent klien | `slug` unik; `status` active/suspended/archived; `log_payloads` + `payload_retention_days` (simpan body request/respons); `image_retention_days`; `default_model` |
| `api_keys` | key gateway | `key_prefix` (`lgw_xxxxxxxx`, tampil di log), `key_hash` = HMAC-SHA256(pepper, key) — **full key tidak pernah disimpan**; `role` client/admin; `scopes`; `rpm_limit`/`tpm_limit` (null = default `.env`); `status` active/revoked, `expires_at`, `revoked_at`, `last_used_at` |
| `project_allowed_models` | pola glob model/route yang boleh dipakai project | `model_pattern` mis. `smart`, `local/*`. Request lewat route harus cocok untuk route **dan** kandidatnya |
| `quotas` | batas per periode | `period` daily/monthly; `max_requests`, `max_tokens`, `max_images`, `max_cost_usd` (null = tanpa batas) |

### Katalog
| Tabel | Isi | Kolom penting |
|---|---|---|
| `providers` | openai, anthropic, gemini, openvino (runtime lokal) | `kind` remote/local; `api_key_env` = **nama** variabel env (nilai key tidak pernah di DB); `timeout_seconds`, `max_concurrency` |
| `models` | model remote & lokal; **sumber kebenaran katalog runtime** | `alias` (`openai/gpt-light`, `local/qwen2.5-7b`); `upstream_name`; `model_type` chat/completion/embedding/image; `tier`; `supports_*`; `device` remote/gpu/npu; `runtime_backend`, `artifact_path`, `artifact_sha256`, `vram_mb`, `is_pinned` (lokal); harga `input_cost_per_mtok`, `output_cost_per_mtok`, `cost_per_image`; `config` (JSON, parameter backend) |
| `model_routes` | alias virtual (`smart`, `code`, ...) | `strategy` priority/round_robin; `config` (mis. `prefer_loaded`) |
| `model_route_targets` | kandidat route | `priority` (kecil = dicoba dulu), `weight` (round robin) |

### Pencatatan
| Tabel | Isi | Kolom penting |
|---|---|---|
| `requests` | satu baris per request API (dibuat `pending` sebelum upstream, difinalisasi setelahnya) | `endpoint`, `requested_model`, `resolved_model_id`, `provider_code`, `device` (gpu/npu untuk lokal, null remote); `status` pending/success/error/cancelled; token, `cost_usd` (Decimal), `latency_ms`, `ttft_ms`, `load_ms`/`queue_ms` (lokal); `attempts`; `caller_task`/`caller_agent` (header `X-Caller-*`); `tags` |
| `request_attempts` | tiap percobaan kandidat (fallback) | `attempt_no`, `provider_code`, `device`, `status`, `error_type`, `latency_ms` |
| `request_payloads` | body request/respons (hanya bila `projects.log_payloads`) | `expires_at` → dihapus retensi |
| `generated_images` | gambar SD yang disimpan untuk `response_format=url` | `file_path` (relatif `storage/`), `seed`, `steps`, `sha256`, `expires_at` |
| `usage_daily` | agregat harian (upsert `ON CONFLICT DO UPDATE`), **tidak pernah dihapus** | PK (`day`, `project_id`, `model_alias`, `provider_code`); counts, token, `image_count`, `cost_usd` |
| `runtime_events` | event Device Manager | `event` load/unload/evict/oom/compile/load_failed/device_error/runtime_start/runtime_stop/queue_timeout; `device`, `duration_ms`, `vram_used_mb`/`vram_budget_mb`, `reason` |
| `audit_logs` | setiap aksi Admin API (atomik dengan perubahannya) | `action` (mis. `key.revoke`), `entity_type`/`entity_id`, `before`/`after` (secret diredaksi), `actor_key_id`, `ip`, `request_id` |

Retensi: lihat `docs/operations.md` (requests 180 hari, audit 730, runtime_events 90, payload &
gambar per project, `usage_daily` permanen).

## Query siap pakai

Jalankan dengan `psql` dari PostgreSQL portable:
```bat
"D:\Data.Fahrul\Documents\PortableDev\postgres\pgsql\bin\psql.exe" -h 127.0.0.1 -U llm_gateway -d llm_gateway
```

**Biaya per project bulan ini** (dari agregat, cepat):
```sql
SELECT p.slug, SUM(u.request_count) AS requests,
       SUM(u.prompt_tokens + u.completion_tokens) AS tokens,
       SUM(u.image_count) AS images, SUM(u.cost_usd) AS cost_usd
FROM usage_daily u JOIN projects p ON p.id = u.project_id
WHERE u.day >= date_trunc('month', now() AT TIME ZONE 'UTC')::date
GROUP BY p.slug ORDER BY cost_usd DESC;
```

**Top 10 request paling lambat 24 jam terakhir:**
```sql
SELECT r.id, p.slug, r.requested_model, r.provider_code, r.device, r.status,
       r.latency_ms, r.ttft_ms, r.load_ms, r.queue_ms, r.attempts, r.created_at
FROM requests r LEFT JOIN projects p ON p.id = r.project_id
WHERE r.created_at > now() - interval '24 hours' AND r.latency_ms IS NOT NULL
ORDER BY r.latency_ms DESC LIMIT 10;
```

**Tingkat error per provider per hari** (per attempt, termasuk yang ter-fallback):
```sql
SELECT date_trunc('day', created_at)::date AS day, provider_code,
       COUNT(*) AS attempts,
       COUNT(*) FILTER (WHERE status <> 'success') AS errors,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status <> 'success') / COUNT(*), 1) AS error_pct
FROM request_attempts
WHERE created_at > now() - interval '14 days'
GROUP BY 1, 2 ORDER BY 1 DESC, 2;
```

**Penelusuran satu `caller_task`:**
```sql
SELECT r.created_at, r.id, r.caller_agent, r.requested_model, r.provider_code, r.device,
       r.status, r.prompt_tokens, r.completion_tokens, r.cost_usd, r.latency_ms
FROM requests r
WHERE r.caller_task = 'ringkas-laporan'
ORDER BY r.created_at;

-- total per task
SELECT caller_task, COUNT(*), SUM(total_tokens), SUM(cost_usd)
FROM requests WHERE caller_task IS NOT NULL
GROUP BY caller_task ORDER BY SUM(cost_usd) DESC NULLS LAST;
```

**Detail fallback satu request** (`X-Request-ID` dari respons):
```sql
SELECT attempt_no, provider_code, device, status, http_status, error_type, latency_ms
FROM request_attempts WHERE request_id = '<uuid>' ORDER BY attempt_no;
```

**Pemakaian device lokal & swap 24 jam terakhir:**
```sql
SELECT device, event, COUNT(*), ROUND(AVG(duration_ms)) AS avg_ms
FROM runtime_events WHERE created_at > now() - interval '24 hours'
GROUP BY 1, 2 ORDER BY 1, 2;
```

**Konsistensi `requests` ↔ `usage_daily`** (harus 0 baris; juga `GET /admin/usage/verify`):
```sql
WITH r AS (
  SELECT (created_at AT TIME ZONE 'UTC')::date AS day, project_id, COUNT(*) AS n
  FROM requests WHERE status <> 'pending' AND project_id IS NOT NULL GROUP BY 1, 2),
u AS (SELECT day, project_id, SUM(request_count) AS n FROM usage_daily GROUP BY 1, 2)
SELECT * FROM r FULL JOIN u USING (day, project_id) WHERE r.n IS DISTINCT FROM u.n;
```
Catatan: `requests` lebih tua dari retensi (180 hari) sudah terhapus sehingga hari-hari lama akan
selalu berbeda; batasi `day` ke 180 hari terakhir.
