# Hardware & keputusan backend (TASK-09)

## Keputusan 28 Oktober 2026

- Model lokal **hanya Qwen + Stable Diffusion v1.5**. Llama, Phi, DeepSeek, nomic-embed, dan bge-m3
  dihapus; embedding dilayani provider remote.
- Semua inferensi lokal lewat **OpenVINO (GenAI) di GPU/NPU**. llama.cpp (`llama-cpp-python`,
  `llama-server`) dihapus beserta seluruh file GGUF.
- **Tidak ada inferensi di CPU**: device selalu eksplisit `GPU`/`NPU` (`CPU`/`AUTO` ditolak), dan
  `cpu_ratio` diukur sebagai bukti.

| Alias | Device | Artefak | vram_mb |
|---|---|---|---|
| local/qwen2.5-7b | GPU | INT4 IR siap pakai (`OpenVINO/Qwen2.5-7B-Instruct-int4-ov`) | 4900 |
| local/qwen2.5-coder-7b | GPU | INT4 IR siap pakai (`OpenVINO/Qwen2.5-Coder-7B-Instruct-int4-ov`) | 5000 |
| local/qwen2.5-coder-1.5b | **NPU** (pinned) | INT4 sym per-channel, konversi sendiri | 2800 |
| local/qwen2-vl-2b | GPU | INT4, konversi sendiri | 2100 |
| local/sd-1.5 | **NPU** (pinned) | INT8, konversi sendiri; text-to-image + image-to-image | 3300 |
| local/qwen3-embedding-0.6b | **GPU** (pinned) | INT8, konversi sendiri; embedding 1024 dim (v1.0.0) | 1800 |

## Keputusan 9 November 2026 — embedding lokal (spike LGW-V1-01)

Menggantikan butir "embedding dilayani provider remote" di atas untuk v1.0.0: **satu-satunya**
model lokal aktif adalah `Qwen/Qwen3-Embedding-0.6B` (lisensi Apache-2.0) di **GPU**, profil
`remote-embed-gpu`. Model lokal lain tetap di disk tetapi nonaktif dan diblokir whitelist runtime.

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Jalur | **OpenVINO GenAI `TextEmbeddingPipeline`** (`runtime_backend: openvino_embed`) | Tokenizer, last-token pooling, dan L2 normalize di dalam pipeline; tanpa torch/optimum di runtime; compile dingin 2,5× lebih cepat dari `optimum.intel` dengan kesetaraan identik |
| Presisi | **INT8** (weight compression `int8_asym` per-channel) | Lulus kesetaraan dengan margin besar; memori & cache ±½ FP16; compile lebih cepat |
| Konversi | `convert_openvino.py --only qwen3-embedding-0.6b-int8` (`--task feature-extraction`) | IR di `local_models/openvino/qwen3-embedding-0.6b-int8`, sha256 `015dc031…a7085e` |
| Batch | `max_batch: 8`, `max_input_tokens: 2048` | Lihat temuan 2 di bawah; angka final di LGW-V1-05 |

**Kesetaraan** (`scripts/spike_embed.py`, set 100 teks `scripts/_embed_eval_set.py`: 30 pendek ID,
30 pendek EN, 20 campur, 20 panjang ±1.220 token, + 20 query dengan prefix instruksi model card).
Referensi = transformers FP32 (pooling token terakhir, padding kiri, L2 normalize), hanya pembanding.
Syarat: kosinus rata-rata ≥ 0,99 dan minimum ≥ 0,98.

| Varian (GPU) | Kosinus rata-rata | Minimum | Compile dingin / cache | Cache | Commit puncak proses | Pendek dok/s b8 / b32 |
|---|---|---|---|---|---|---|
| GenAI FP16 | 0,99995 | 0,99963 | 10,2 s / 2,5 s | 1.197 MB | +2.963 MB | 37,8 / 35,2 |
| **GenAI INT8** | **0,99860** | **0,99721** | **7,0 s / 1,4 s** | **605 MB** | **+2.015 MB** | **41,7 / 47,0** |
| optimum FP16 | 0,99995 | 0,99963 | 19,7 s / 2,8 s | 1.197 MB | +3.751 MB | 39,2 / 43,7 |
| optimum INT8 | 0,99863 | 0,99724 | 18,2 s / 1,5 s | 605 MB | +2.866 MB | 44,5 / 47,7 |

Semua varian lulus; kategori terendah INT8 = query (0,99721). Jumlah token dari tokenizer OpenVINO
sama persis dengan tokenizer HF (diuji `tests/hardware/test_embed.py`).

**Memori perangkat** (counter `GPU Process Memory`, backend runtime sungguhan, INT8):

| Beban | Puncak | Token/s |
|---|---|---|
| setelah load (bobot + warmup) | 608–776 MB | – |
| batch 8 × ±1.670 token | **1.274 MB** | 417 |
| batch 16 × ±1.670 token | 2.577 MB | 418 |
| batch 32 × ±1.670 token | 4.250 MB | 444 |

Budget GPU 5.300 MB → `vram_mb: 1800` (b8 × 2.048 token ≈ 1.500 MB + margin) muat dengan sisa
±3,5 GB; tidak ada model GPU lain di profil ini.

### Temuan spike
1. **Throughput iGPU dibatasi komputasi**, bukan compile ulang per shape: batch shape identik
   berulang sama lambatnya (0,34 dok/s untuk teks ±1.220 token). Kira-kira **±420–440 token/s**
   untuk chunk panjang, **±730 token/s** untuk teks pendek (±15 token). Proyeksi kasar: 1 juta
   token (buku ±2.000 chunk × 500 token) ≈ 40 menit. Benchmark lengkap = LGW-V1-05.
2. **Batch besar tidak menambah token/s untuk teks panjang tetapi memori naik tajam** (b32 = 4,25 GB,
   hampir seluruh budget GPU). Karena itu `max_batch: 8`. Batas berbasis jumlah token per batch
   layak dipertimbangkan di LGW-V1-04/05.
3. Compile pertama INT8 ±7 s, dari cache ±1,4 s → warmup model pinned saat start cepat.

## Hasil probe (`scripts\probe_devices.py`, detail: `logs\device_probe.json`)

| Komponen | Hasil |
|---|---|
| CPU | Intel Core Ultra 5 225 (Arrow Lake), 10 core |
| GPU | **Intel Graphics (iGPU), terintegrasi / UMA**: tidak ada VRAM khusus. `GPU_DEVICE_TOTAL_MEM_SIZE` ≈ 7983 MB adalah batas alokasi dari RAM sistem bersama. |
| NPU | Intel AI Boost (arsitektur 3720), driver 1004778, `NPU_DEVICE_TOTAL_MEM_SIZE` = 8192 MB (juga dari RAM sistem bersama) |
| RAM | **15.740 MB total** |
| OpenVINO | 2026.4.1 (`openvino`, `openvino-tokenizers`, `openvino-genai` satu versi) |
| Python | 3.11.17 (conda env `llm-genai`) |

## Memori: GPU & NPU = RAM sistem (UMA)

Di mesin ini GPU dan NPU **tidak punya memori sendiri**; keduanya mengambil dari RAM 15,7 GB yang
juga dipakai Windows, PostgreSQL, gateway, dan runtime. Memindahkan model ke GPU/NPU memindahkan
**komputasi** dari CPU, tetapi bobot model tetap menempati RAM. Karena itu budget GPU+NPU harus
menyisakan RAM untuk sistem.

Budget yang dipakai (`.env`, `.env.example`):

| | Total | Reserve | Budget | Isi |
|---|---|---|---|---|
| GPU | 6000 | 700 | **5300 MB** | satu model GPU aktif (7B 4900–5000 MB, atau VL 2100 MB), bergantian lewat LRU |
| NPU | 6500 | 300 | **6200 MB** | SD 3300 + Coder-1.5B 2800 = 6100 MB, keduanya pinned |

Validasi (`measure_models.py --validate-only`): GPU 5000/5300 OK, NPU 6100/6200 OK, total maks
**11.100 MB (71% RAM)** → ±4,5 GB tersisa untuk OS & layanan. `GPU_RESERVE_MB=700` menampung
pool plugin GPU yang tetap tertahan ±670 MB setelah model di-unload.

## Pengukuran (`measure_models.py`, `test_sd.py`), cache compile sudah hangat

Prompt uji 541 dan ±1.500 token, 128 token keluaran. Memori = counter Windows
`GPU Process Memory (Dedicated + Shared)` untuk proses pengukur (mencakup NPU).

| Alias | Device | Load | TTFT 541 tok | TTFT ±1,5K tok | Token/s | cpu_ratio | Puncak |
|---|---|---|---|---|---|---|---|
| local/qwen2.5-7b | GPU | 5,2 s | 6,1 s | 16,1 s | 7,2–8,3 | ~1,0 | 4.576 MB |
| local/qwen2.5-coder-7b | GPU | 2,5 s | 5,9 s | 14,4 s | 8,4–8,8 | ~1,0 | 4.690 MB |
| local/qwen2.5-coder-1.5b | NPU | 3,1 s | 1,7 s | 3,3 s | 19,3–20,5 | **0,03–0,08** | 2.590 MB |
| local/qwen2-vl-2b | GPU | 3,9 s | 1,6 s | 4,7 s | 24,5–27,5 | ~1,0 | 1.970 MB |

| SD v1.5 INT8, NPU (text_encoder + UNet + VAE) | Hasil |
|---|---|
| Compile pertama / dengan cache | 118 s / **3,3 s** (35×) |
| text-to-image 512², 20 step | 20,6 s, deterministik (seed sama → PNG identik) |
| image-to-image 512², strength 0,6 | 13,3 s |
| cpu_ratio | **0,01–0,02** |
| Memori perangkat / RSS | 3.094 MB / 5.324 MB (satu set model untuk dua mode) |
| FP16 (pembanding) | compile 137 s, t2i 21,3 s, memori 3.119 MB, RSS 6.046 MB → **INT8 dipilih** (kecepatan & kualitas setara, RAM lebih kecil) |

### Arti `cpu_ratio`
Waktu CPU proses ÷ waktu dinding selama generate (10 core → nilai maksimal ±10).
- **NPU ±0,01–0,08**: CPU praktis menganggur.
- **GPU ±1,0**: satu thread host plugin GPU (submit/sinkronisasi kernel) sibuk penuh, ±10% dari
  total CPU. Ini overhead driver, bukan inferensi; inferensi CPU akan bernilai ±6–10.

### Dibanding llama.cpp (Vulkan, diukur 27 Okt, sudah dihapus)

| | llama.cpp Vulkan | OpenVINO |
|---|---|---|
| Qwen2.5-7B generate | 3,5 token/s | 7,2–8,3 token/s (±2,3×) |
| Qwen2.5-7B prefill | ±28 token/s | ±90–100 token/s |
| Coder-1.5B generate | 13,4 token/s (GPU) | 20 token/s (NPU), 27–28 token/s (GPU) |
| Pemakaian NPU | tidak bisa | bisa |

## Temuan penting

1. **LLM di NPU wajib INT4 simetris per-channel** (`--sym --group-size -1 --ratio 1.0`). IR
   `OpenVINO/*-int4-ov` (asimetris, group 128) dan hasil konversi default ditolak compiler NPU:
   `StopLocationVerifierPass ... Found 142 duplicated names` (dicoba pada Coder-1.5B & Qwen2-VL).
   Konversi 7B sendiri butuh ±15 GB RAM (tidak mungkin di mesin ini), jadi model 7B di GPU.
2. **Compile pertama memakan ±2× memori**: Qwen2.5-7B di GPU puncak 8.023 MB dan 28 s tanpa cache,
   4.391 MB dan 5 s dengan cache. Cache harus dihangatkan sekali setelah instalasi (smoke test /
   measure sudah melakukannya); runtime sebaiknya tidak cold-compile 7B saat model lain dimuat.
   Cache untuk kelima model ±12,5 GB di disk (`local_models/ov_cache`; blob GPU ikut menyimpan
   bobot). Bila cache dihapus, jalankan ulang `smoke_local.py` + `test_sd.py` (±5 menit).
3. **SD lewat OpenVINO GenAI berjalan penuh di NPU.** Jalur lama `optimum` (`OVStableDiffusionPipeline`)
   macet > 60 menit saat compile UNet. `Text2ImagePipeline(image2image_pipe)` berbagi model, sehingga
   memori turun dari 4,5 GB → 3,1 GB (perangkat) dan 10 GB → 5,3 GB (RSS).
4. **NPU dipakai bersama SD dan Coder-1.5B.** Request autocomplete bisa menunggu selama SD
   generate (±20 s). Bila latensi autocomplete lebih penting, Coder-1.5B bisa dipindah ke GPU
   (27 token/s, IR GPU harus diunduh ulang) dengan konsekuensi berbagi GPU dengan model 7B.
5. **FIM Coder-1.5B di NPU** (TASK-11): prefill NPU berjalan per chunk statis, jadi TTFT
   ditentukan ukuran chunk, bukan panjang prompt. Hasil ukur (first token, prompt 20 / 237 token):

   | `NPUW_LLM_PREFILL_CHUNK_SIZE` | prompt 20 tok | prompt 237 tok | prompt 454 tok |
   |---|---|---|---|
   | default (MAX_PROMPT_LEN 2048) | 1.597 ms | – | 1.743 ms |
   | 512 | 463 ms | – | 465 ms |
   | **256 (dipakai)** | **254 ms** | **254 ms** | 514 ms |
   | 128 | 150 ms | 292 ms | 583 ms |

   Katalog: `prefill_chunk_size: 256`, `fim_max_prompt_tokens: 256` → TTFT end-to-end lewat
   backend **251 ms** (target NF11 < 300 ms terpenuhi). Konteks FIM ±256 token (±20–30 baris
   sekitar kursor) adalah kompromi latensi; naikkan `fim_max_prompt_tokens` bila kualitas lebih
   penting (±500 ms untuk 512 token).
6. **Tool calling & JSON**: `Tokenizer.apply_chat_template(..., tools=[...])` menyisipkan definisi
   tools lewat template Qwen native; output `<tool_call>` di-parse `runtime/backends/tool_parsers.py`.
   `StructuredOutputConfig(json_schema=...)` menghasilkan JSON valid. Keduanya lolos smoke test.
7. **Konversi Qwen2-VL** butuh transformers ≤ 5.0 (batas optimum-intel 2.2); `convert_openvino.py`
   memasangnya terpisah di `local_models/convert_deps/` (hanya untuk proses konversi).
8. **Unduhan**: jalur `huggingface_hub`/Xet macet di 0 byte pada jaringan ini; semua unduhan lewat
   `scripts/_hfhttp.py` (HTTPS, resume, retry). `conda-run.bat` menyetel `HF_HUB_DISABLE_XET=1`.

## Smoke test (`docs/smoke/`)

| Alias | Device | Uji | Hasil |
|---|---|---|---|
| local/qwen2.5-7b | GPU | tool call `get_weather(Bandung)` + JSON schema | OK |
| local/qwen2.5-coder-7b | GPU | `slugify` + unit test pytest | OK |
| local/qwen2.5-coder-1.5b | NPU | FIM `is_prime`, dieksekusi | OK |
| local/qwen2-vl-2b | GPU | gambar sintetis (kotak merah + "GATEWAY 42") | OK |
| local/sd-1.5 | NPU | text-to-image + image-to-image (`sd15_t2i.png`, `sd15_i2i.png`) | OK |

## Cara mengulang

```bat
scripts\conda-run.bat python scripts\probe_devices.py
scripts\conda-run.bat python scripts\download_models.py --write-yaml     :: Qwen2.5 7B (IR siap pakai)
scripts\conda-run.bat python scripts\convert_openvino.py --write-yaml    :: SD INT8, Qwen2-VL, Coder-1.5B NPU, Qwen3-Embedding
scripts\conda-run.bat python scripts\spike_embed.py                      :: kesetaraan embedding (LGW-V1-01)
scripts\conda-run.bat python scripts\test_sd.py                          :: 2× (cek cache)
scripts\conda-run.bat python scripts\smoke_local.py                      :: juga menghangatkan cache
scripts\conda-run.bat python scripts\measure_models.py --update-yaml     :: setelah cache hangat
scripts\conda-run.bat alembic upgrade head
scripts\conda-run.bat python scripts\manage.py seed --update-local
```
Jalankan pengukuran satu model per proses dan tutup aplikasi berat lain.
