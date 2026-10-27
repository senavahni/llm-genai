# Hardware & keputusan backend (TASK-09)

Hasil `scripts\probe_devices.py` (detail mentah: `logs\device_probe.json`), 27 Oktober 2026.

| Komponen | Hasil |
|---|---|
| CPU | Intel Core Ultra 5 225 (Arrow Lake) |
| GPU | **Intel Graphics (iGPU), terintegrasi / UMA**: tidak ada GPU diskrit. OpenVINO melaporkan `GPU_DEVICE_TOTAL_MEM_SIZE` ≈ 7983 MB, tetapi itu batas alokasi dari RAM sistem bersama, bukan VRAM khusus. |
| NPU | Intel AI Boost (arsitektur 3720), driver 1004778, `NPU_DEVICE_TOTAL_MEM_SIZE` = 8192 MB (juga dari RAM sistem bersama) |
| RAM | **15.740 MB total**; saat probe hanya ~3.570 MB tersedia (aplikasi lain aktif) |
| OpenVINO | 2026.4.1, device: `CPU`, `GPU`, `NPU` |
| llama-cpp-python | 0.3.36, wheel **Vulkan**; `llama_supports_gpu_offload()` = `True`; `ggml_vulkan: Intel(R) Graphics | uma: 1 | fp16: 1 | int dot: 1` |
| Python | 3.11.17 (conda env `llm-genai`) |

## Keputusan

| Pertanyaan | Jawaban | Dampak |
|---|---|---|
| Vendor GPU? | Intel (iGPU) | `LLAMA_GPU_BACKEND=vulkan`, wheel `.../whl/vulkan` (sudah terpasang, ter-pin di `requirements-local.txt`) |
| NPU Intel terdeteksi OpenVINO? | Ya (`NPU`) | SD v1.5 & bge-m3 bisa di NPU |
| Device OpenVINO `GPU` tersedia? | Ya (iGPU Intel) | Opsi `component_devices` SD (mis. VAE ke `GPU`) tersedia, tetapi memorinya sama dengan budget GPU llama.cpp |

## ⚠ Selisih dengan asumsi PRD (§5.2, §7.5)

PRD mengasumsikan **GPU 8 GB + NPU 8 GB** yang terpisah. Di mesin ini GPU dan NPU sama-sama
memakai **RAM sistem 15,7 GB yang sama**, yang juga dipakai Windows, PostgreSQL, gateway, dan
runtime. Budget default (`GPU 7200 + NPU 7500 = 14.700 MB`) **tidak muat** di RAM fisik; bila
terisi penuh, Windows akan paging berat atau driver gagal alokasi.

Usulan (perlu diputuskan, lalu diubah di `.env`):

| Opsi | GPU budget | NPU budget | Konsekuensi |
|---|---|---|---|
| A. Satu model 7B + pinned kecil | `GPU_TOTAL_MB=7600`, `GPU_RESERVE_MB=600` → 7000 | `NPU_TOTAL_MB=3700`, `NPU_RESERVE_MB=300` → 3400 | Total ≈ 10,4 GB; sisa ≈ 5 GB untuk OS & layanan. Model 7–8B tetap bisa dipakai bergantian. |
| B. Tanpa 7B lokal (hemat) | 4500 | 3400 | Route `smart`/`code`/`local` mengandalkan remote atau model 3B; jauh lebih aman. |
| C. Tetap PRD | 7200 | 7500 | Tidak disarankan di mesin ini. |

Nilai `vram_mb` di katalog masih **perkiraan PRD** sampai `measure_models.py` dijalankan untuk
tiap model (lihat bawah).

## Katalog GGUF (terverifikasi `download_models.py --dry-run`)

Semua repo & nama file ada di Hugging Face; total unduhan **27,09 GB**.

| Alias | File | Ukuran |
|---|---|---|
| local/qwen2.5-7b | bartowski/Qwen2.5-7B-Instruct-GGUF · `Qwen2.5-7B-Instruct-Q4_K_M.gguf` | 4,68 GB |
| local/qwen2.5-coder-7b | bartowski/Qwen2.5-Coder-7B-Instruct-GGUF · `Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf` | 4,68 GB |
| local/qwen2.5-coder-1.5b | Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF · `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` | 1,12 GB |
| local/qwen2-vl-2b | bartowski/Qwen2-VL-2B-Instruct-GGUF · `Qwen2-VL-2B-Instruct-Q4_K_M.gguf` + `mmproj-...-f16.gguf` | 2,32 GB |
| local/llama-3.2-3b | bartowski/Llama-3.2-3B-Instruct-GGUF · Q4_K_M | 2,02 GB |
| local/llama-3.1-8b | bartowski/Meta-Llama-3.1-8B-Instruct-GGUF · Q4_K_M | 4,92 GB |
| local/phi-3.5-mini | bartowski/Phi-3.5-mini-instruct-GGUF · Q4_K_M | 2,39 GB |
| local/deepseek-r1-qwen-7b | bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF · Q4_K_M | 4,68 GB |
| local/nomic-embed | nomic-ai/nomic-embed-text-v1.5-GGUF · F16 | 0,27 GB |

OpenVINO (dikonversi `convert_openvino.py`): `sd15-fp16`, `sd15-int8`, `bge-m3-int8`.

## Pengukuran (`measure_models.py`, `test_npu.py`)

Metode memori iGPU: performance counter Windows `GPU Process Memory (Dedicated + Shared Usage)`
untuk PID proses pengukur.

| Alias | n_ctx | Load | TTFT (prompt 3.116 token) | Token/s | Puncak | vram_mb | Catatan |
|---|---|---|---|---|---|---|---|
| local/qwen2.5-coder-1.5b | 4096 | 0,87 s | 17,2 s | 13,4 | 1.389 MB | **1500** (PRD: 1300) | Vulkan iGPU; memori kembali ~0 setelah unload; sha256 tercatat |
| 10 model lainnya | | | | | | perkiraan PRD | belum diunduh/diukur |

Catatan Coder-1.5B: prefill prompt panjang di iGPU ≈ 180 token/s. Untuk autocomplete FIM
(prompt pendek ±300–800 token) TTFT diperkirakan ±2–4 detik, jauh di atas target NF11
(p50 < 300 ms). Ukur ulang dengan prompt FIM realistis di TASK-11/20.

Validasi budget dengan nilai saat ini (`measure_models.py --validate-only`):
- GPU: pinned 1500 + swap terbesar 5800 (perkiraan llama-3.1-8b) = **7300 > 7192 MB → MELEBIHI**
- NPU: pinned 3200 / 7492 MB → OK
- UMA: total maks 10.500 MB dari RAM 15.740 MB (67%)

## Cara mengulang

```bat
call scripts\env.bat
"%PY%" scripts\probe_devices.py
"%PY%" scripts\download_models.py --write-yaml          :: ~27 GB
"%PY%" scripts\convert_openvino.py                      :: SD fp16/int8 + bge-m3 int8
"%PY%" scripts\test_npu.py                              :: jalankan 2x (cek cache compile)
"%PY%" scripts\measure_models.py --update-yaml          :: satu per satu, tutup aplikasi lain
"%PY%" scripts\manage.py seed --update-local            :: sinkron vram_mb/sha256/path ke DB
```
