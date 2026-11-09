# Task v1.0.0 — LLM Gateway (Embedding Lokal OpenVINO GPU & Dukungan Market Intelligence)

> Draf brainstorming rev. 2 · 9 November 2026.
> Hub lintas repo (keputusan V1-K1…K21, alur F1–F5, biaya, kriteria rilis): `mcp/documentation/v1.0.0/README.md`.
> Task MCP: `mcp/documentation/v1.0.0/TASKS.md` · Task Dashboard: `marketingdashboardjtp/Documentation/v1.0.0/V1_TASKS.md`.
> DoD mengikuti `llm_gateway_docs_v2/tasks/README.md` **tanpa pengecualian** — termasuk butir 5: model lokal tidak berjalan di CPU.

## Ringkasan

| Keputusan | Isi |
|---|---|
| Model lokal | **Satu-satunya**: `Qwen/Qwen3-Embedding-0.6B` (≙ `qwen3-embedding:0.6b`), OpenVINO IR, **GPU**, 1024 dim, alias `local/qwen3-embedding-0.6b`, route `embed-local` |
| Model lokal lain | Qwen2.5-7B, Coder-7B, Coder-1.5B, Qwen2-VL-2B, SD-1.5 **tetap nonaktif, tidak di-compile, tidak dimuat** (artefak tetap di disk) |
| Ollama | Tidak dipakai |
| Route remote | `smart` = gpt-5 · `creative` = Claude Sonnet 5.5 → gpt-5 · `extract` = gpt-5-mini (hanya LLM assist) · `fast`, `embed-default` tetap |
| Profil aktif v1 | **`remote-embed-gpu`** (menggantikan `remote-only`); `start-all.bat` **dengan** runtime |

Kondisi awal: profil `remote-only`; runtime punya backend `ov_llm`, `ov_vlm`, `ov_diffusion` (`runtime/backends/`) tetapi **tidak ada backend embedding**; `app/services/embedding_service.py` praktis remote dan `local_runtime_provider` belum melayani embedding.

## Daftar Task

| ID | Task | Fase | Prio | Est. | Dependensi |
|---|---|---|---|---|---|
| LGW-V1-01 | **Spike**: ekspor Qwen3-Embedding-0.6B → OpenVINO IR, kesetaraan, memori GPU | 1 | P0 | 1 pd | — |
| LGW-V1-02 | Backend runtime `openvino_embed` (GPU) + `/embeddings` di runtime & provider lokal | 1 | P0 | 3 pd | 01 |
| LGW-V1-03 | Profil `remote-embed-gpu`, whitelist runtime, route `embed-local`, key agent baru | 1 | P0 | 1,5 pd | 02 |
| LGW-V1-04 | Embedding volume besar: batch, panjang input, `input_type`, `dimensions`, prioritas | 1 | P0 | 2 pd | 02 |
| LGW-V1-05 | Benchmark kapasitas & kualitas di GPU target | 1 | P0 | 1,5 pd | 02–04 |
| LGW-V1-06 | Route `creative`/`extract`, structured output, tag usage per job, plafon budget | 3 | P0 | 2 pd | — |
| LGW-V1-07 | Testing, dokumentasi, rilis v1.0.0 | 6 | P0 | 1,5 pd | semua |

**Total ±12,5 pd.** LGW-V1-01 → 02 → 03 memblokir semua embedding 1024 di MCP.

### Urutan mulai di repo ini
1. **LGW-V1-01 spike** — hari pertama; risiko teknis terbesar seluruh v1.
2. **LGW-V1-02** backend → **LGW-V1-03** profil & whitelist (setelah ini MCP bisa mulai MCP-V1-01/04).
3. **LGW-V1-06** dapat dikerjakan paralel (tidak bergantung runtime).

---

## LGW-V1-01 — Spike ekspor & kesetaraan

| Dependensi | — | Referensi | `docs/model-catalog.md` §Menambah model lokal, `docs/hardware.md`, TASK-09 |
|---|---|---|---|

**Tujuan:** Membuktikan Qwen3-Embedding-0.6B berjalan benar di GPU lewat OpenVINO sebelum membangun backend.

**Langkah**
1. Unduh `Qwen/Qwen3-Embedding-0.6B` (cek lisensi model card; catat di katalog).
2. Bandingkan dua jalur:
   - `optimum-cli export openvino --task feature-extraction` + `optimum.intel.OVModelForFeatureExtraction`;
   - OpenVINO GenAI `TextEmbeddingPipeline` (bila mendukung arsitektur Qwen3).
3. Varian presisi: FP16 dan INT8 (weight compression) di **GPU**.
4. **Kesetaraan:** 100 teks Indonesia/Inggris (pendek, panjang ±1.000 token, campur) → kosinus vs referensi PyTorch/HF (pooling last-token, L2 normalize, prompt query sesuai model card) **≥ 0,99** rata-rata, ≥ 0,98 minimum.
5. Ukur: waktu compile pertama, ukuran cache, memori puncak (UMA), throughput kasar batch 8/32.
6. Simpan IR di `local_models/openvino/qwen3-embedding-0.6b-<prec>` + `artifact_sha256`.

**Output:** catatan keputusan di `docs/hardware.md` (jalur terpilih, presisi, angka). **Bila kedua jalur gagal** → eskalasi ke pemilik produk sebelum melanjutkan (opsi: model embedding lain yang didukung OpenVINO di GPU dengan dimensi 1024).

**Acceptance Criteria:** salah satu jalur lulus kesetaraan di GPU dan memori muat dalam budget GPU (`GPU_TOTAL_MB − GPU_RESERVE_MB`).

---

## LGW-V1-02 — Backend runtime `openvino_embed`

| Dependensi | 01 | Referensi | `runtime/backends/base.py`, `ov_common.py`, `local_runtime_provider.py`, `embedding_service.py` |
|---|---|---|---|

**Spesifikasi**
- `runtime/backends/ov_embed_backend.py`: muat IR jalur terpilih di **device GPU** (tanpa fallback CPU kecuali `ALLOW_CPU_FALLBACK=true` di test), tokenisasi dengan padding sesuai model (last-token pooling butuh posisi token terakhir yang benar), L2 normalize, batch.
- `runtime_backend: openvino_embed` di katalog/migrasi bila enum dibatasi; device manager memperlakukan model sebagai **pinned** (selalu termuat, tidak ikut swap).
- Endpoint runtime `/v1/embeddings` (auth `RUNTIME_TOKEN`) → `local_runtime_provider.embed()` → `EmbeddingService` (router & usage yang ada). Usage: jumlah token dari tokenizer (bukan perkiraan), biaya 0, device `gpu` tercatat.
- Health runtime: model termuat, device, memori; `/health` Gateway melaporkan `embed-local` degraded bila runtime mati.

**Pengujian:** unit backend dengan model palsu; hardware test (`-m gpu`) memakai set kesetaraan LGW-V1-01; runtime mati → error terstruktur `provider_unavailable`.

**Acceptance Criteria:** `POST /v1/embeddings {model: "local/qwen3-embedding-0.6b"}` → vektor 1024 dari GPU, setara dengan hasil spike.

---

## LGW-V1-03 — Profil `remote-embed-gpu`, whitelist, route, key

| Dependensi | 02 | Referensi | `scripts/profiles/*.yaml`, `manage.py apply-profile`, M3_TASK_009 |
|---|---|---|---|

**Spesifikasi**
- Profil `remote-embed-gpu`: provider `openvino` aktif **hanya** untuk `local/qwen3-embedding-0.6b`; semua model lokal lain `is_enabled=false`; route `local`, `autocomplete`, `image`, `vision`-lokal tetap mati; route remote seperti `remote-only`.
- **Whitelist runtime:** setting `RUNTIME_ALLOWED_MODELS` (diisi profil). Runtime **menolak load/compile/warmup** model di luar whitelist (log + error), termasuk lewat Admin API `cache/reload` atau `smoke_local.py`; `manage.py verify-models` hanya memverifikasi model whitelist.
- Route `embed-local`: kandidat tunggal `local/qwen3-embedding-0.6b`, **tanpa fallback** ke model berdimensi lain. `embed-default` (1536) tidak berubah.
- Project `marketing-mcp` `allowed-models` + `embed-local`, `local/qwen3-embedding-*`; key agent baru **`creative`, `curator`, `prospector`** (skrip provisioning MCP); pola per key: `prospector` hanya `extract` + `embed-local`; `curator` `smart` + `embed-local`; `creative` `creative` + `embed-local`.
- `start-all.bat` default menyalakan runtime dengan profil ini.

**Acceptance Criteria:** setelah `apply-profile remote-embed-gpu` + restart, `/health` runtime menunjukkan **hanya** satu model termuat di GPU; upaya load model lain ditolak (test); MCP memanggil `embed-local` dengan key agent.

---

## LGW-V1-04 — Embedding volume besar

| Dependensi | 02 | Referensi | `app/services/embedding_service.py` |
|---|---|---|---|

**Spesifikasi**
- Batch splitting ≤ 2.048 input → batch backend (`config.max_batch`), urutan output dijaga.
- Panjang input: cek token terhadap `config.max_input_tokens`; lewat → `400 input_too_long` + indeks, atau potong bila `provider_options.truncate=true` (+ `X-Gateway-Warning`).
- `provider_options.input_type ∈ {query, document}`; model config `embedding_instructions {query: "Instruct: <tugas>\nQuery: ", document: ""}` diterapkan Gateway.
- `dimensions` hanya bila model mendukung (MRL) — selain itu 400 jelas.
- **Prioritas:** header `X-Priority: interactive|bulk`; antrean runtime melayani `interactive` lebih dulu sehingga pencarian/klasifikasi tidak tertahan ingest buku/import; batas konkurensi `bulk`.

**Pengujian:** urutan output, input terlalu panjang, prefix hanya untuk query, prioritas (interactive selesai < X ms saat ada beban bulk), regresi `embed-default`.

**Acceptance Criteria:** MCP mengirim batch tanpa mengatur batch/prefix sendiri; klien lama tidak terpengaruh.

---

## LGW-V1-05 — Benchmark di GPU target

**Spesifikasi**
- Throughput (chunk/detik) untuk 200/500/800/1.000 token × batch 8/16/32/64; memori puncak; latensi `interactive` di bawah beban `bulk`.
- Proyeksi: buku 500 halaman (±1.500–2.500 chunk), import 1.000 baris (klasifikasi), 100 perusahaan × 8 halaman.
- Kualitas: set 30 pertanyaan ID/EN (bersama MCP-V1-18) → recall@6 `embed-local` vs `embed-default`.
- Tetapkan default `max_batch`, `max_input_tokens`, konkurensi `bulk`, target waktu ingest untuk MCP-V1-11.

**Acceptance Criteria:** bagian "Embedding lokal (GPU)" di `docs/perf-report.md` terisi angka terukur + rekomendasi.

---

## LGW-V1-06 — Route `creative`/`extract`, structured output, tag usage, budget

**Spesifikasi**
- Route `creative`: `anthropic/claude-sonnet` → `openai/gpt-heavy` (tanpa `ANTHROPIC_API_KEY` → langsung gpt-5). Route `extract`: `openai/gpt-light` (JSON mode).
- Verifikasi `response_format: json_schema` per adapter; kandidat yang tidak mendukung dilewati.
- **Tag usage:** header `X-Request-Tags: job=…,kind=…,stage=…,agent=…` (≤ 5 pasang, tanpa PII) → kolom `tags jsonb` + GIN (migrasi `0005_usage_tags`); `GET /admin/usage/by-tag?key=job|kind|agent&from&to`.
- **Plafon budget** project `marketing-mcp` (usul $150/bulan) memakai mekanisme kuota yang ada; peringatan 80%.

**Acceptance Criteria:** biaya satu job dapat dihitung per tahap/agent dari Gateway; tag tidak valid diabaikan + warning.

---

## LGW-V1-07 — Testing, dokumentasi, rilis v1.0.0

**Checklist**
- [ ] Test unit/integrasi 01–06; hardware test `-m gpu` untuk embedding; secret scan.
- [ ] `docs/model-catalog.md`: hapus "tidak ada embedding lokal", tambah `local/qwen3-embedding-0.6b` (sumber, lisensi, sha256, `vram_mb` terukur), route `embed-local`/`creative`/`extract`, profil `remote-embed-gpu`, aturan whitelist. `docs/client-integration.md`: `input_type`, `X-Priority`, `X-Request-Tags`, batas input. `docs/operations.md`: start dengan runtime, troubleshooting GPU.
- [ ] `.env.example`, `seed_models.yaml`, `scripts/profiles/`.
- [ ] `pyproject.toml` → `1.0.0`, `CHANGELOG.md`, tag `v1.0.0`; E2E lintas repo F1–F5 bersama MCP-V1-19 & DSH-V1-14.

**Acceptance Criteria:** stack tiga project berjalan dengan `remote-embed-gpu`; hanya Qwen3-Embedding termuat; kriteria rilis lintas repo lulus.
