# TASK-09 — Hardware Probe, Instalasi OpenVINO & Akuisisi Model Lokal

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 2 hari (termasuk waktu unduh & konversi) |
| Dependensi | TASK-01, TASK-04 |
| Referensi PRD | §5.2, §7.4, §7.5, §9.4, §9.5 |

> **Revisi 28 Okt 2026 (keputusan pemilik proyek):** model lokal hanya **keluarga Qwen +
> Stable Diffusion v1.5**, semuanya dijalankan **OpenVINO di GPU/NPU, tanpa CPU**. llama.cpp
> (`llama-cpp-python`, `llama-server`), model non-Qwen (Llama, Phi, DeepSeek), dan embedding lokal
> (bge-m3, nomic) dihapus. Embedding dilayani provider remote. Alasan & data:
> `docs/hardware.md`.

## Tujuan
Memastikan GPU dan NPU terdeteksi OpenVINO, memasang stack OpenVINO (runtime + GenAI), mengunduh /
mengonversi model katalog ke OpenVINO IR, dan **mengukur memori & performa aktual** tiap model
di device tujuannya untuk mengisi `models.vram_mb`.

## Katalog model lokal

| Alias | Device | Backend | Artefak | Sumber |
|---|---|---|---|---|
| `local/qwen2.5-7b` | GPU | `openvino_llm` | INT4 IR | `OpenVINO/Qwen2.5-7B-Instruct-int4-ov` (siap pakai) |
| `local/qwen2.5-coder-7b` | GPU | `openvino_llm` | INT4 IR | `OpenVINO/Qwen2.5-Coder-7B-Instruct-int4-ov` (siap pakai) |
| `local/qwen2.5-coder-1.5b` | NPU | `openvino_llm` | INT4 sym per-channel | konversi dari `Qwen/Qwen2.5-Coder-1.5B-Instruct` |
| `local/qwen2-vl-2b` | GPU | `openvino_vlm` | INT4 IR | konversi dari `Qwen/Qwen2-VL-2B-Instruct` |
| `local/sd-1.5` | NPU | `openvino_diffusion` | INT8 IR | konversi dari `stable-diffusion-v1-5/stable-diffusion-v1-5` |

Penempatan device final ditentukan dari pengukuran langkah 6 dan dicatat di `docs/hardware.md`.

## Langkah

### 0. Prasyarat Python
Env conda `llm-genai` (Python 3.11). Semua perintah lewat `scripts\conda-run.bat`, yang
mengaktifkan Miniconda + env dan menyetel `HF_HOME`, `OV_CACHE_DIR`, `HF_HUB_DISABLE_XET`.

### 1. Identifikasi hardware — `scripts/probe_devices.py`
Output ke `logs/device_probe.json` dan layar: `openvino.Core().available_devices` (wajib memuat
`GPU` dan `NPU`), properti tiap device (`FULL_DEVICE_NAME`, `DEVICE_TYPE` integrated/discrete,
`*_DEVICE_TOTAL_MEM_SIZE`, driver NPU), versi `openvino` & `openvino_genai`, RAM total/tersedia.
GPU terintegrasi (UMA) berarti memori GPU **dan** NPU diambil dari RAM sistem yang sama; ini
masuk perhitungan budget. Device `CPU` tidak dipakai sebagai target inferensi.

### 2. Instal stack OpenVINO
```bat
scripts\conda-run.bat pip install -r requirements-local.txt
scripts\conda-run.bat python -c "import openvino as ov, openvino_genai as g; print(ov.__version__, g.__version__, ov.Core().available_devices)"
```
- `openvino`, `openvino-tokenizers`, `openvino-genai` **harus satu versi** (ter-pin).
- `optimum-intel`, `nncf`, `transformers`, torch CPU hanya untuk **konversi**; runtime tidak
  memakai torch.
- `llama-cpp-python` tidak dipasang.

### 3. Unduh IR siap pakai — `scripts/download_models.py`
- Model dengan `hf_repo` IR siap pakai (tanpa `convert: true`) diunduh utuh ke `artifact_path`.
- Unduhan lewat `scripts/_hfhttp.py` (HTTPS biasa, resume `Range`, retry, cek ukuran), karena
  jalur `huggingface_hub`/Xet macet di jaringan ini.
- `--write-yaml` menulis `artifact_sha256` = digest folder IR (sha256 tiap file, path terurut;
  `runtime/core/artifacts.py`). Opsi `--only`, `--dry-run`.

### 4. Konversi — `scripts/convert_openvino.py` (wrapper `optimum-cli`)
Bobot sumber diunduh ke `local_models/hf_src/` lalu dikonversi offline (`HF_HUB_OFFLINE=1`):
```bat
scripts\conda-run.bat python scripts\convert_openvino.py --only sd15-int8,qwen2-vl-2b-int4,qwen2.5-coder-1.5b-int4-npu
```
- **LLM untuk NPU wajib INT4 simetris per-channel** (`--weight-format int4 --sym --group-size -1
  --ratio 1.0`). IR `OpenVINO/*-int4-ov` (asimetris, group 128) ditolak compiler NPU.
- Konversi model 7B butuh RAM ±2× ukuran FP16 (±15 GB): **jangan konversi 7B di mesin ini**,
  pakai IR siap pakai.
- SD v1.5: FP16 dan INT8 (`--task text-to-image`); keduanya memuat `vae_encoder` untuk
  image-to-image.

### 5. Uji SD — `scripts/test_sd.py` (OpenVINO GenAI)
- `Image2ImagePipeline(path)` → `reshape(1, 512, 512, guidance_scale)` →
  `compile(text_encoder_dev, unet_dev, vae_dev, CACHE_DIR=...)`, lalu `Text2ImagePipeline(i2i)`
  memakai model yang sama (tidak dimuat dua kali).
- Generate text-to-image 2× dengan seed sama (harus identik) dan image-to-image dari hasilnya.
- Catat waktu compile pertama & kedua (cache), waktu generate, memori perangkat, RSS, dan
  `cpu_ratio`. Bila sebuah komponen gagal di NPU, coba `--devices NPU,GPU,NPU` dan catat
  kombinasi yang berhasil di `models.config.component_devices`.

### 6. Ukur memori & performa LLM — `scripts/measure_models.py`
Untuk setiap model Qwen, **satu per satu** (`--device GPU|NPU` untuk membandingkan):
1. Catat memori perangkat proses sebelum load: counter Windows
   `\GPU Process Memory(pid_*)\Dedicated Usage + Shared Usage` (semua adapter, termasuk NPU) via
   `typeperf`; RSS proses sebagai pembanding.
2. Load `LLMPipeline`/`VLMPipeline(path, device, CACHE_DIR=..., [MAX_PROMPT_LEN, MIN_RESPONSE_LEN untuk NPU])`.
3. Generate 128 token untuk prompt 512 dan 2048 token: TTFT, token/s (`perf_metrics`), dan
   **`cpu_ratio` = waktu CPU proses / waktu dinding** sebagai bukti inferensi tidak di CPU.
4. `vram_mb` = (puncak − sebelum) × 1,05, dibulatkan ke atas ke kelipatan 100 MB.
5. Unload dan catat memori setelahnya.

Hasil → `logs/measure_models.json`, `docs/hardware.md`, `scripts/seed_models.yaml` (`--update-yaml`)
→ `manage.py seed --update-local`.

**Validasi budget** (otomatis di akhir script): pinned + swap terbesar per device ≤ budget, dan
total GPU+NPU dibandingkan RAM fisik (UMA).

### 7. Smoke test kualitas — `scripts/smoke_local.py`
- Qwen2.5-7B: tool call `get_weather` lewat template chat native (`apply_chat_template(..., tools=...)`)
  + parser Hermes; JSON terstruktur via `StructuredOutputConfig(json_schema=...)`.
- Coder-1.5B (NPU): FIM fungsi Python, hasil dieksekusi.
- Coder-7B: fungsi + unit test.
- Qwen2-VL-2B: deskripsi gambar uji.
- SD: text-to-image & image-to-image (langkah 5).
Output di `docs/smoke/`.

### 8. Sinkron katalog ke DB
```bat
scripts\conda-run.bat alembic upgrade head          :: 0002: backend OpenVINO, model lama → retired
scripts\conda-run.bat python scripts\manage.py seed --update-local
```
`--update-local` menyamakan semua kolom model lokal dengan yaml, mengaktifkan ulang model katalog,
dan menonaktifkan model lokal yang tidak ada lagi di yaml (tercatat di `audit_logs`).

## Deliverables
- [ ] `scripts/probe_devices.py`, `download_models.py`, `convert_openvino.py`, `test_sd.py`,
      `measure_models.py`, `smoke_local.py`, `_hfhttp.py`, `conda-run.bat`
- [ ] `requirements-local.txt` (openvino, openvino-tokenizers, openvino-genai, optimum-intel, nncf, ter-pin)
- [ ] `scripts/seed_models.yaml` (repo, sha256, license, device, backend, vram_mb, config)
- [ ] Migrasi `0002_openvino_backends`
- [ ] `docs/hardware.md` (probe, keputusan device, tabel memori & performa, `cpu_ratio`)
- [ ] Folder `local_models/` terisi (tidak di-commit)

## Acceptance Criteria
1. `ov.Core().available_devices` memuat `GPU` dan `NPU`; `openvino_genai` terpasang dengan versi sama.
2. Kelima model katalog terunduh/terkonversi dengan sha256 tercatat.
3. SD v1.5 text-to-image & image-to-image 512² berjalan di NPU (atau kombinasi NPU/GPU
   terdokumentasi); compile kedua memakai cache (≥ 5× lebih cepat); seed sama → gambar identik.
4. `vram_mb` terukur untuk semua model di device katalognya, dan skenario budget lolos validasi.
5. Tidak ada model yang berjalan di CPU: device eksplisit `GPU`/`NPU` (tanpa `AUTO`/`CPU`) dan
   `cpu_ratio` selama generate jauh di bawah jumlah core (inferensi CPU ≈ jumlah core).
