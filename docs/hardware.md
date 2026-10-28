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
5. **FIM Coder-1.5B di NPU: TTFT 1,7 s untuk prompt 541 token**, jauh dari target NF11 (p50 < 300 ms).
   Prompt FIM perlu dibatasi ±128–256 token; diukur ulang di TASK-11.
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
scripts\conda-run.bat python scripts\convert_openvino.py --write-yaml    :: SD INT8, Qwen2-VL, Coder-1.5B NPU
scripts\conda-run.bat python scripts\test_sd.py                          :: 2× (cek cache)
scripts\conda-run.bat python scripts\smoke_local.py                      :: juga menghangatkan cache
scripts\conda-run.bat python scripts\measure_models.py --update-yaml     :: setelah cache hangat
scripts\conda-run.bat alembic upgrade head
scripts\conda-run.bat python scripts\manage.py seed --update-local
```
Jalankan pengukuran satu model per proses dan tutup aplikasi berat lain.
