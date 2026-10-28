# TASK-18 — Health Check & Metrics

| Item | Nilai |
|---|---|
| Milestone | M5 Governance |
| Prioritas | P1 |
| Estimasi | 1 hari |
| Dependensi | TASK-06, TASK-10, TASK-15 |
| Referensi PRD | §10.4, F15 |

## Tujuan
Memberi sinyal kesehatan untuk script start, Traefik, dan pemantauan sederhana.

## Spesifikasi

### `app/routes/health.py` (tanpa auth)
- `GET /health/live` → `{"status":"ok","version":...,"uptime_s":...}`.
- `GET /health/ready` →
```json
{"status":"ready|degraded|not_ready",
 "database":{"ok":true,"latency_ms":2},
 "providers":{"openai":{"ok":true},"llamacpp":{"ok":true},"openvino":{"ok":true}},
 "runtime":{"ok":true,"devices":{"gpu":{"ok":true,"used_mb":1300,"budget_mb":7200},
                                 "npu":{"ok":true,"used_mb":3200,"budget_mb":7500}},
            "pinned_loaded":{"local/qwen2.5-coder-1.5b":true,"local/sd-1.5":true,"local/bge-m3":true}}}
```
  - `not_ready` (HTTP 503) bila DB gagal.
  - `degraded` (HTTP 200) bila ≥1 provider enabled gagal, runtime mati, salah satu device tidak OK, atau ada model pinned yang belum termuat.
  - Hasil provider di-cache 15 detik; health check provider dijalankan paralel dengan timeout 3 detik.
  - Detail error provider hanya ditampilkan bila request berasal dari `127.0.0.1` atau membawa admin key.

### Health Local Runtime (`runtime/routes/health.py`)
- `GET /health/live` (tanpa token).
- `GET /health/ready` (token): `ready` bila device yang dibutuhkan OK dan semua model pinned termuat. Selama warmup/compile NPU pertama → 503 `warming_up` dengan progres (`loaded 2/3`).

### Metrics — `app/utils/metrics.py` (`prometheus_client`)
| Metric | Tipe | Label |
|---|---|---|
| `gateway_requests_total` | Counter | endpoint, provider, model, status |
| `gateway_request_latency_seconds` | Histogram | endpoint, provider |
| `gateway_ttft_seconds` | Histogram | provider |
| `gateway_tokens_total` | Counter | provider, model, kind (prompt/completion) |
| `gateway_cost_usd_total` | Counter | provider, model |
| `gateway_upstream_errors_total` | Counter | provider, error_type |
| `gateway_inflight_requests` | Gauge | endpoint |
| `gateway_fallbacks_total` | Counter | route |
| `gateway_requests_by_device_total` | Counter | device (remote/gpu/npu/cpu) |
| `gateway_images_total` | Counter | model |
| `runtime_device_memory_used_mb` | Gauge | device |
| `runtime_device_memory_budget_mb` | Gauge | device |
| `runtime_model_loaded` | Gauge (0/1) | model, device, pinned |
| `runtime_model_load_seconds` | Histogram | model, device |
| `runtime_evictions_total` | Counter | model, device |
| `runtime_oom_total` | Counter | model, device |
| `runtime_queue_wait_seconds` | Histogram | model |
| `runtime_queue_depth` | Gauge | model |
| `runtime_tokens_per_second` | Histogram | model |
| `runtime_image_seconds` | Histogram | model, size |

- Label **tidak** memuat project/key (hindari kardinalitas tinggi; detail per project ada di DB).
- `GET /metrics` → `generate_latest()`; akses dibatasi ke localhost atau admin key.
- Metrik `gateway_*` diupdate dari `usage_service.finish` dan `chat_service`.
- Metrik `runtime_*` diekspos runtime di `GET /metrics` miliknya (token). Gateway menggabungkannya ke `/metrics` gateway dengan fetch ber-cache 10 detik, sehingga cukup satu endpoint scrape.
- `gateway_requests_by_device_total{device="cpu"}` harus 0 di produksi (dipakai sebagai alarm NF9).

## Deliverables
- [x] `app/routes/health.py`, `app/utils/metrics.py` (+ `health_service.py`, `health_controller.py`,
      `runtime/core/metrics.py`, runtime `GET /metrics` ber-token, progres warmup di runtime
      `/health/ready`)
- [x] `scripts/healthcheck.py` (dipakai `start-all.bat` untuk menunggu runtime & gateway siap; mendukung header token)

> Catatan 28 Okt 2026: contoh JSON di atas masih menyebut `llamacpp`/`bge-m3`; katalog sekarang
> hanya provider `openvino` dengan pinned `local/qwen2.5-coder-1.5b` & `local/sd-1.5`.

## Acceptance Criteria
1. Matikan PostgreSQL → `/health/ready` 503 `not_ready`; matikan runtime → 200 `degraded` dengan `runtime.ok=false`.
1b. Selama compile NPU pertama, runtime `/health/ready` 503 `warming_up`; setelah selesai menjadi `ready`.
2. `/metrics` dapat di-parse format Prometheus dan nilainya bertambah setelah request.
3. `/health/live` merespons < 10 ms.
4. `/metrics` gateway memuat metrik `runtime_*` (memori GPU/NPU, model termuat).
