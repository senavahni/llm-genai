# TASK-09 — Hardware Probe, Instalasi Akselerator & Akuisisi Model Lokal

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 2 hari (termasuk waktu unduh & konversi) |
| Dependensi | TASK-01, TASK-04 |
| Referensi PRD | §5.2, §7.4, §7.5, §9.4, §9.5 |

## Tujuan
Memastikan GPU dan NPU terdeteksi oleh library yang dipakai, memasang `llama-cpp-python` versi GPU serta OpenVINO, mengunduh/mengonversi seluruh model katalog, dan **mengukur VRAM aktual** tiap model untuk mengisi `models.vram_mb`.

## Langkah

### 0. Prasyarat Python
Di Conda Prompt:
```bat
conda activate llm-genai
python --version
```
Versi harus **3.10–3.12** (wheel prebuilt `llama-cpp-python`). Bila versi lain, buat env baru `conda create -n llm-genai-py311 python=3.11` dan perbarui `CONDA_ENV` di `scripts\env.bat`.

### 1. Identifikasi hardware — `scripts/probe_devices.py`
Output JSON ke `logs/device_probe.json` dan ke layar:
- **OpenVINO:** `openvino.Core().available_devices` (harus memuat `NPU`; `GPU` muncul bila GPU Intel), lalu untuk tiap device: `FULL_DEVICE_NAME`, `GPU_DEVICE_TOTAL_MEM_SIZE` (bila ada), driver/`DEVICE_ARCHITECTURE`.
- **NVIDIA:** `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv` (bila perintah ada), CUDA version dari header `nvidia-smi`.
- **llama.cpp:** setelah langkah 2, `llama_cpp.llama_supports_gpu_offload()` dan daftar device ggml dari log `verbose=True`.

Keputusan yang dihasilkan dan dicatat di `docs/hardware.md`:
| Pertanyaan | Dampak |
|---|---|
| Vendor GPU? (NVIDIA / Intel Arc / AMD) | `LLAMA_GPU_BACKEND=cuda` atau `vulkan` |
| NPU Intel terdeteksi di OpenVINO? | Wajib untuk SD v1.5 & bge-m3. Jika tidak terdeteksi, cek driver NPU di Device Manager. Driver biasanya sudah terpasang bawaan laptop Core Ultra; pemasangan driver butuh admin, jadi minta bantuan IT bila belum ada. |
| Device OpenVINO `GPU` tersedia? | Opsi `component_devices` SD (mis. VAE ke GPU) |

### 2. Instal `llama-cpp-python` (GPU)
```bat
rem NVIDIA (pilih cuXXX sesuai CUDA yang didukung driver: cu121..cu125, cu130, cu132)
pip install llama-cpp-python --prefer-binary --only-binary=llama-cpp-python ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

rem Intel Arc / AMD (Vulkan)
pip install llama-cpp-python --prefer-binary --only-binary=llama-cpp-python ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/vulkan
```
- `--only-binary` mencegah build dari source, yang butuh compiler.
- Bila DLL CUDA runtime tidak ditemukan: `conda install -c nvidia cuda-runtime=12.4` (berjalan tanpa admin di env user), lalu pastikan `env.bat` memuat `Library\bin`.
- Verifikasi:
```bat
python -c "import llama_cpp; print(llama_cpp.__version__, llama_cpp.llama_supports_gpu_offload())"
```
  Hasil harus `True`.
- **Rencana cadangan:** unduh binary resmi `llama.cpp` (varian `win-cuda` atau `win-vulkan`) ke `PortableDev\llama.cpp\` untuk `runtime_backend=llama_server` (TASK-11).
- Catat versi wheel di `requirements-local.txt` (pin).

### 3. Instal OpenVINO
```bat
pip install openvino "optimum[openvino]" diffusers transformers huggingface_hub safetensors pillow
python -c "import openvino as ov; print(ov.__version__, ov.Core().available_devices)"
```
Torch hanya dibutuhkan saat **konversi** (dependensi optimum). Inferensi runtime tidak memakai torch. Pakai torch CPU-only untuk konversi agar ringan:
```bat
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### 4. Unduh model GGUF — `scripts/download_models.py`
- Membaca `scripts/seed_models.yaml`, berisi per model: `alias`, `hf_repo`, `filename` (boleh pola, mis. shard `*-00001-of-*.gguf`), `mmproj_filename`, `sha256` (opsional), `license`.
- Pakai `huggingface_hub.hf_hub_download(local_dir=local_models/gguf, ...)` (resume otomatis).
- Hitung `sha256` setelah unduh lalu tulis kembali ke yaml / DB (`models.artifact_sha256`).
- Opsi `--only alias1,alias2` dan `--dry-run` (tampilkan ukuran total).

Contoh repo (**verifikasi nama file & kuantisasi saat implementasi**; pilih Q4_K_M):

| Alias | Contoh repo HF | Catatan |
|---|---|---|
| `local/qwen2.5-7b` | `Qwen/Qwen2.5-7B-Instruct-GGUF` | Repo resmi bisa menyimpan Q4_K_M sebagai beberapa shard. Muat dari shard pertama, llama.cpp menggabungkan otomatis. |
| `local/qwen2.5-coder-7b` | `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` | sama |
| `local/qwen2.5-coder-1.5b` | `Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF` atau GGUF varian **base** | Base lebih baik untuk FIM. Uji keduanya di langkah 7. |
| `local/qwen2-vl-2b` | `ggml-org/Qwen2-VL-2B-Instruct-GGUF` / `bartowski/Qwen2-VL-2B-Instruct-GGUF` | Butuh `mmproj-*.gguf` |
| `local/llama-3.2-3b` | `bartowski/Llama-3.2-3B-Instruct-GGUF` | Lisensi Llama 3.2 Community |
| `local/llama-3.1-8b` | `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` | Lisensi Llama 3.1 Community |
| `local/phi-3.5-mini` | `bartowski/Phi-3.5-mini-instruct-GGUF` | MIT |
| `local/deepseek-r1-qwen-7b` | `bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF` | MIT |
| `local/nomic-embed` | `nomic-ai/nomic-embed-text-v1.5-GGUF` | Apache-2.0; varian F16 |

Total unduhan ≈ 26 GB. Pastikan ruang disk ≥ 40 GB, termasuk hasil konversi dan cache.

### 5. Konversi OpenVINO — `scripts/convert_openvino.py` (wrapper `optimum-cli`)
```bat
rem Stable Diffusion v1.5 (FP16 dan INT8)
optimum-cli export openvino --model stable-diffusion-v1-5/stable-diffusion-v1-5 ^
  --weight-format fp16 local_models\openvino\sd15-fp16
optimum-cli export openvino --model stable-diffusion-v1-5/stable-diffusion-v1-5 ^
  --weight-format int8 local_models\openvino\sd15-int8

rem Embedding bge-m3
optimum-cli export openvino --model BAAI/bge-m3 --task feature-extraction ^
  --weight-format int8 local_models\openvino\bge-m3-int8
```
- Repo SD v1.5 lama (`runwayml/...`) sudah tidak tersedia; gunakan `stable-diffusion-v1-5/stable-diffusion-v1-5` atau model OpenVINO pra-konversi dari organisasi `OpenVINO` di HF bila tersedia.
- Variabel `HF_HOME` harus mengarah ke `local_models\hf_cache`.

### 6. Uji kompilasi NPU (standalone)
Script `scripts/test_npu.py`:
- SD: `OVStableDiffusionPipeline.from_pretrained(path, compile=False, ov_config={"CACHE_DIR": OV_CACHE_DIR})` → `reshape(batch_size=1, height=512, width=512, num_images_per_prompt=1)` → `to("NPU")` → `compile()` → generate 1 gambar 20 step. Catat waktu compile pertama dan kedua (dengan cache), serta waktu generate.
- Bila op tidak didukung di NPU: uji varian FP16 vs INT8, lalu per-komponen (`text_encoder`, `unet`, `vae_decoder`) ke device berbeda. Catat kombinasi yang berhasil di `docs/hardware.md` dan isi `models.config.component_devices`.
- bge-m3: `OVModelForFeatureExtraction.from_pretrained(path, device="NPU", compile=False)` → `reshape(8, 512)` → `compile()` → encode 8 kalimat.

### 7. Ukur VRAM & performa — `scripts/measure_models.py`
Untuk setiap model GGUF, **satu per satu**:
1. Catat memori GPU sebelum load.
   - NVIDIA: `pynvml`, `nvmlDeviceGetMemoryInfo`.
   - Intel/AMD (Vulkan): Windows performance counter `\GPU Process Memory(*)\Dedicated Usage` via `typeperf` atau `psutil` untuk PID proses; cocokkan dengan Task Manager.
2. Load dengan `config` dari §9.4 PRD (`n_gpu_layers=-1`, `flash_attn`, KV q8_0, `n_ctx` default).
3. Jalankan prompt panjang (≈ 80% `n_ctx`) agar KV cache terisi, lalu generate 128 token.
4. Catat memori puncak − sebelum = `vram_mb` (dibulatkan ke atas ke kelipatan 100 MB + 5% margin), throughput token/s, TTFT, dan waktu load.
5. Unload dan pastikan memori kembali.

Untuk NPU: catat memori proses sebelum/sesudah compile (NPU Intel memakai memori sistem bersama), lalu isi `vram_mb` sebagai bagian budget NPU.

Hasil → `docs/hardware.md` (tabel) + `scripts/seed_models.yaml` (`vram_mb`) → `manage.py seed --update-local` memperbarui DB.

**Validasi budget:** script menghitung skenario PRD §7.5:
- pinned GPU + model swap terbesar ≤ 7200 MB,
- semua pinned NPU ≤ 7500 MB.

Bila melebihi, turunkan `n_ctx` / pakai KV q4_0 / ganti mmproj ke Q8, lalu ulang.

### 8. Smoke test kualitas singkat
- Qwen2.5-7B & Llama-3.1-8B: tool calling sederhana (`get_weather`).
- Coder-1.5B: FIM (lengkapi isi fungsi Python).
- Coder-7B: tulis fungsi + unit test.
- Qwen2-VL-2B: deskripsikan gambar uji.
- DeepSeek-R1: soal aritmetika bertahap (cek tag `<think>`).
- SD: 1 gambar 512².
- bge-m3/nomic: kemiripan kosinus pasangan kalimat ID/EN.
Simpan output di `docs/smoke/` sebagai bukti.

## Deliverables
- [ ] `scripts/probe_devices.py`, `download_models.py`, `convert_openvino.py`, `test_npu.py`, `measure_models.py`
- [ ] `requirements-local.txt` (versi ter-pin: llama-cpp-python, openvino, optimum-intel, diffusers, transformers)
- [ ] `scripts/seed_models.yaml` lengkap (repo, file, sha256, license, device, backend, vram_mb, config)
- [ ] `docs/hardware.md` (hasil probe, keputusan backend, tabel VRAM & performa)
- [ ] Folder `local_models/` terisi (tidak di-commit)

## Acceptance Criteria
1. `llama_supports_gpu_offload()` = `True`; `ov.Core().available_devices` memuat `NPU`.
2. Seluruh 11 model katalog (9 GGUF + SD v1.5 + bge-m3) (§7.4 A–C) terunduh/terkonversi dengan sha256 tercatat.
3. SD v1.5 berhasil generate 512² di NPU; bge-m3 berjalan di NPU; compile kedua memakai cache (≥ 5× lebih cepat).
4. `vram_mb` terukur untuk semua model, dan skenario budget §7.5 lolos validasi.
5. Tidak ada model yang dijalankan di CPU selama pengukuran (verifikasi log llama.cpp: semua layer offloaded; device OpenVINO = NPU/GPU).
