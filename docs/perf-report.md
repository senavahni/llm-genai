# Laporan performa & QA (TASK-20)

Mesin target: Intel Core Ultra 5 225 (10 core), iGPU Intel Graphics + NPU Intel AI Boost,
RAM 15,7 GB (GPU & NPU memakai RAM sistem), Windows 11, OpenVINO 2026.4.1, Python 3.11.
Tanggal: 28 Oktober 2026.

## Ringkasan

| Target | Hasil | Status |
|---|---|---|
| NF1 overhead non-stream p95 < 30 ms | 10 ms @25 RPS, 14 ms @50 RPS, 42 ms @100 RPS; jenuh ±75–110 RPS | ✅ s/d ±80 RPS, deviasi di atasnya |
| NF1 TTFT tambahan < 50 ms | p50 60 ms / p95 197 ms pada 50 stream bersamaan (±78 stream/detik) | ⚠️ deviasi (beban sangat tinggi) |
| NF2 ≥ 50 stream bersamaan, 1 worker | 50 stream × 2 menit, 9.312 stream, 0 error | ✅ |
| NF9 0 request lokal di CPU | MARK_NF9 | MARK_NF9_STATUS |
| NF10 memori ≤ budget, 0 OOM pada swap | MARK_NF10 | MARK_NF10_STATUS |
| NF11 lokal | lihat tabel benchmark | lihat di bawah |
| Secret scan | 0 temuan (logs + DB dev + DB uji) | ✅ |
| Coverage ≥ 70% (`app/services`, `app/utils`, `runtime/device`, `runtime/services`) | MARK_COV | ✅ |

## Kualitas kode & test

`scripts\check.bat`: ruff check, ruff format --check, mypy `app` + `runtime`
(`disallow_untyped_defs` untuk `app.services.*`, `app.utils.*`, `runtime.*`), pytest + coverage,
secret scan. Hasil: MARK_CHECK.

| Jenis | Lokasi | Dijalankan |
|---|---|---|
| Unit | `tests/unit/` (utils, translator, router, ratelimit, kuota, biaya, runtime device manager, parser tool) | `scripts\test.bat` |
| Integrasi | `tests/integration/` (API + PostgreSQL nyata, provider palsu) | `scripts\test.bat` |
| Contract | `tests/contract/` (SDK `openai` resmi → uvicorn sungguhan, port acak) | `scripts\test.bat` |
| Load | `tests/load/` (gateway di proses terpisah) | `scripts\test.bat tests\load --load -s` |
| Live | `tests/live/` (provider remote asli lewat gateway berjalan) | `scripts\test.bat tests\live --live` |
| Hardware | `tests/hardware/` (backend langsung + end-to-end lewat gateway) | `scripts\test-hardware.bat` |
| Benchmark | `tests/bench/bench_local.py` | `scripts\bench.bat` |

Kasus wajib TASK-20 yang tidak berlaku lagi: parser tool `llama3_json` (model Llama dihapus;
hanya `hermes` untuk Qwen), embedding lokal (bge-m3 / nomic dihapus).

## Load test (provider palsu)

Gateway di proses terpisah (`tests/load/fake_gateway.py`, 1 worker uvicorn, logging file seperti
produksi, pencatatan usage ke PostgreSQL aktif), generator beban di proses pytest pada mesin
yang sama. Data mentah: `logs\load-results.json`.

### Skenario B — non-stream, open-loop, 30 detik per langkah
| Target RPS | Tercapai | Error | p50 | p95 | p99 |
|---|---|---|---|---|---|
| 25 | 25,0 | 0 | 7,7 ms | 10,1 ms | 11,6 ms |
| 50 | 50,0 | 0 | 8,9 ms | 14,1 ms | 18,9 ms |
| 100 | 100,0 | 0 | 14,3 ms | 41,9 ms | 173,8 ms |
| 200 | 75,1 | 302 (503, ReadError) | 12,9 s | 53,7 s | 59,5 s |

### Skenario A — 50 stream bersamaan × 120 detik (provider 25 chunk × 20 ms)
9.312 stream, 0 error. Overhead TTFT p50 60 ms / p95 197 ms; overhead total stream p50 125 ms /
p95 342 ms.

### Deviasi NF1 & penyebab
- **Kapasitas 1 worker ±80–110 RPS** (bukan 200). Profil (`cProfile`, 500 request berurutan):
  ±6–9 ms CPU per request, didominasi pencatatan ke PostgreSQL (±10 round-trip: `INSERT`
  request `pending` sebelum upstream + transaksi finalisasi 7 statement di latar) dan kompilasi
  statement SQLAlchemy ORM, ditambah event loop Proactor Windows (tanpa uvloop). Di atas
  kapasitas, antrean tumbuh, pool DB habis → 503 `service_unavailable` (by design: request tidak
  diproses tanpa pencatatan).
- **TTFT tambahan > 50 ms pada 50 stream bersamaan**: pada ±78 stream/detik × 25 chunk (±2.000
  event SSE/detik) event loop jenuh; pada beban rendah TTFT tambahan ≈ overhead non-stream
  (< 15 ms).
- **Dampak praktis rendah**: beban nyata gateway ini dibatasi model (7B lokal ±7 token/s; remote
  dibatasi rate limit provider), jauh di bawah 80 RPS.
- **Rekomendasi bila perlu**: (1) write-behind batch untuk finalisasi usage (satu transaksi untuk
  banyak request), (2) `INSERT` awal tanpa ORM (Core + statement cache), (3) skala horizontal
  hanya setelah state rate limit/kuota dipindah ke PostgreSQL/Redis (saat ini wajib 1 worker).

## Model lokal

MARK_HARDWARE

<!-- bench:start -->
_Diukur 2026-10-28 07:47 UTC lewat gateway (`tests/bench/bench_local.py`)._

| Model (FIM) | TTFT p50 | TTFT p95 | token/s | runs |
|---|---|---|---|---|
| local/qwen2.5-coder-1.5b | 262 ms | 272 ms | 21.5 | 20 |

| Model (chat) | prompt tok | output tok | TTFT (tanpa load) | token/s | load model |
|---|---|---|---|---|---|
| local/qwen2-vl-2b (+gambar) | 293 | 256 | 2.65 s | 30.2 | 5.3 s |

| Model (gambar) | detik/gambar 512², 25 step (median) | tercepat | runs |
|---|---|---|---|
| local/sd-1.5 | 25.3 s | 25.1 s | 3 |

| Model gagal diukur | Error |
|---|---|
| local/qwen2.5-7b | /v1/chat/completions 502: b'{"error":{"message":"Semua kandidat gagal (local/qwen2.5-7b: model_load_failed)","type":"upstream_error","code":"all_candidates_fail |
| local/qwen2.5-coder-7b | /v1/chat/completions 502: b'{"error":{"message":"Semua kandidat gagal (local/qwen2.5-coder-7b: model_load_failed)","type":"upstream_error","code":"all_candidate |

<!-- bench:end -->

## RAM sistem

MARK_RAM

## Live smoke (provider remote)

Belum dijalankan: `.env` belum berisi `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
(provider remote nonaktif otomatis; `/health/ready` menampilkan alasannya). Adapter remote diuji
dengan mock HTTP (`tests/unit/providers/`). Setelah key diisi:
```bat
set LGW_TEST_KEY=lgw_...    :: key dengan akses anthropic/*, openai/*, gemini/*
scripts\test.bat tests\live --live -v
```
lalu catat hasilnya di sini (model, non-stream/stream, usage, header provider).
