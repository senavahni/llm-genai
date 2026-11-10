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

## Embedding lokal (GPU) — v1.0.0 (LGW-V1-05)

Diukur 10 November 2026, `local/qwen3-embedding-0.6b` (INT8, `TextEmbeddingPipeline`, iGPU),
`scripts\conda-run.bat python scripts\bench_embed.py throughput|latency|quality`; JSON mentah di
`local_models/spike/bench/`. Kesetaraan vs PyTorch & keputusan presisi: `docs/hardware.md`.

### Throughput × batch (chunk/detik, token/detik, memori perangkat)

| Token/chunk | b8 | b16 | b32 | b64 |
|---|---|---|---|---|
| 200 | **5,21** (1.043 tok/s) | 5,19 (1.039) | 4,90 (980) | 4,70 (941) |
| 500 | **1,57** (785) | 1,65 (824) | 1,60 (799) | 1,59 (793) |
| 800 | **0,94** (752) | 0,85 (680) | 0,84 (671) | tidak diukur¹ |
| 1.000 | **0,68** (676) | 0,64 (636) | 0,63 (633) | tidak diukur¹ |

Memori perangkat (counter `GPU Process Memory`, puncak kumulatif proses — pool plugin GPU tidak
mengecil): 676 MB setelah load; 1.250 MB setelah b8×500; 2.265 MB setelah b8×1.000; 2.534 MB
b64×500; 2.331 MB b32×1.000. ¹ > 32.768 token ber-padding per batch, dilewati (berisiko melewati
budget GPU 5.300 MB / RAM UMA; spike: b32 × 1.670 token = 4.250 MB).

**Kesimpulan:** iGPU dibatasi komputasi — batch > 8 tidak mempercepat (malah sedikit melambat)
tetapi menambah memori. Throughput bergantung panjang chunk: ±1.040 token/s (200 token) turun ke
±680 token/s (1.000 token, biaya atensi).

### Latensi interactive saat ada beban bulk

Job bulk 96 chunk × 500 token (`X-Priority: bulk`), query interactive (1 teks pendek ber-prefix)
setiap 2 detik; idle (tanpa bulk) ±70–100 ms.

| `max_batch_tokens` | Interactive p50 | p95 | maks | Bulk chunk/s |
|---|---|---|---|---|
| 1.024² | 913 ms | 1.551 ms | 1.714 ms | 1,36 |
| **2.048 (default)** | **1.018 ms** | **1.600 ms** | 2.304 ms | 1,24–1,40 |
| 4.096 | 3.538 ms | 3.815 ms | 4.139 ms | 1,46 |

Interactive dilayani di antara batch bulk (antrean prioritas per batch), jadi latensinya ≈ sisa
satu batch bulk + inferensinya sendiri. ² Nilai < `max_input_tokens` (2.048) dinaikkan otomatis
ke 2.048 oleh backend, sehingga 2.048 adalah batas bawah efektif dan dipilih sebagai default.
Ukuran pertama (sebelum interactive memegang satu lease untuk rencana + batch-nya) p50 3,8 s —
sudah diperbaiki.

### Kualitas (set eval KB MCP: 3 brief → 24 chunk per bagian, 30 pertanyaan ID)

| Model | recall@1 | recall@3 | recall@6 |
|---|---|---|---|
| `embed-local` (query + prefix instruksi, `input_type=query`) | **0,733** | **0,967** | 0,967 |
| `embed-local` tanpa prefix | 0,667 | 0,933 | 1,000 |
| `embed-default` (`openai/text-embedding-3-small`) | 0,700 | 0,933 | 1,000 |

Dense saja (tanpa hybrid/keyword MCP). Kualitas setara `embed-default`; pool kecil membuat @6
jenuh sehingga @1/@3 lebih membedakan. Target MCP-V1-04 (recall@6 hybrid ≥ 0,85) diuji di MCP.

### Proyeksi (bulk, 1 job, tanpa beban interactive berat)

| Beban | Asumsi | Perkiraan |
|---|---|---|
| Buku 500 halaman | 1.500–2.500 chunk × 500 token @ ±1,4–1,6 chunk/s | **±16–30 menit** |
| Import 1.000 baris (klasifikasi) | teks ±50 token, ±18 baris/s (interpolasi dari 15 & 200 token, tidak diukur langsung) | **±1 menit** |
| 100 perusahaan × 8 halaman | 800–1.600 chunk × 800 token @ ±0,9 chunk/s | **±15–30 menit** |

Rumus kasar untuk MCP: menit ≈ total token ÷ 42.000 (±700 token/s).

### Rekomendasi & default yang ditetapkan

| Parameter | Nilai | Catatan |
|---|---|---|
| `max_batch` | 8 | tercepat/setara dengan memori terkecil |
| `max_input_tokens` | 2.048 | MCP chunk ≤ 1.024 token sudah aman; lebih panjang → `input_too_long` atau `truncate` |
| `max_batch_tokens` | 2.048 | interactive p95 ±1,6 s di bawah bulk |
| `RUNTIME_BULK_CONCURRENCY` | 1 | job bulk antre FIFO; tidak saling memperlambat |
| Ukuran request bulk dari MCP | ≤ 64 chunk (≤ 1.024 token) per request | ±1,5 menit per request, jauh di bawah timeout provider 300 s & `RUNTIME_BULK_QUEUE_TIMEOUT_S` |
| Target ingest MCP-V1-11 | ≥ 1,2 chunk/s (500 token) | buku 2.000 chunk < 30 menit |

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
