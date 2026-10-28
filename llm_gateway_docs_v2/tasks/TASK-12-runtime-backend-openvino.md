# TASK-12 — Runtime Backend OpenVINO: Stable Diffusion v1.5 (Text-to-Image & Image-to-Image) di NPU

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 2 hari |
| Dependensi | TASK-09, TASK-10 |
| Referensi PRD | §7.4 A#2 & C, §8.4, §9.4 |

> **Revisi 28 Okt 2026:** embedding lokal (bge-m3) dihapus dari katalog. SD v1.5 dijalankan dengan
> pipeline **OpenVINO GenAI** (`Image2ImagePipeline` + `Text2ImagePipeline` berbagi model), bukan
> `optimum` + diffusers, sehingga runtime tidak membutuhkan torch. Mode baru: image-to-image.

## Tujuan
Menjalankan **Stable Diffusion v1.5** text-to-image dan image-to-image di **NPU** (atau kombinasi
NPU/GPU per komponen yang terdokumentasi), tanpa jatuh ke CPU, dengan cache kompilasi, hasil
deterministik, dan antrean yang aman.

## `runtime/backends/ov_diffusion_backend.py` (`kind="openvino_diffusion"`)

### Load
```python
i2i = openvino_genai.Image2ImagePipeline(spec.artifact_path)
i2i.reshape(1, H, W, guidance_scale)                  # shape statis NPU (v1: 512x512)
i2i.compile(dev["text_encoder"], dev["unet"], dev["vae"], CACHE_DIR=OV_CACHE_DIR)
t2i = openvino_genai.Text2ImagePipeline(i2i)          # berbagi model: tidak dimuat dua kali
```
- Device per komponen dari `cfg.component_devices` (default semua `"NPU"`), hanya `NPU`/`GPU`.
  `CPU`/`AUTO` ditolak validator kecuali `ALLOW_CPU_FALLBACK=true`.
- `guidance_scale` ikut menentukan shape statis (batch UNet 2× bila guidance > 1), jadi nilai
  `guidance_scale` dari caller dibatasi ke nilai saat compile (`cfg.guidance_scale`, default 7.5)
  atau ditolak 400. Variasi guidance membutuhkan pipeline terpisah (dihitung ke `vram_mb`).
- Satu pipeline per ukuran di `allowed_sizes` (v1: hanya `512x512`).
- Catat `runtime_events(event='compile', duration_ms, details={"cache_hit": bool})`.
  Terukur di TASK-09: compile pertama ±2 menit, dengan cache ±3 detik.

### Generate (text-to-image, `/v1/images/generations`)
```json
{"model":"sd15", "prompt":"...", "negative_prompt":"...", "n":1, "size":"512x512",
 "steps":25, "guidance_scale":7.5, "seed":42, "response_format":"b64_json"}
```
- `t2i.generate(prompt, negative_prompt=..., num_inference_steps=steps,
  generator=CppStdGenerator(seed), callback=on_step)` di thread device NPU, `Semaphore(1)` per
  pipeline.
- `n` gambar dibuat berurutan dengan `seed + i`. Seed acak (dicatat) bila tidak dikirim. Hasil
  deterministik untuk seed & parameter yang sama (terverifikasi TASK-09).
- Output tensor uint8 `[1, H, W, 3]` → PNG (Pillow) di memori → `b64` + `sha256` + `bytes` +
  metadata (`seed`, `steps`, `guidance_scale`, `width`, `height`, `infer_ms`). Penyimpanan file
  untuk `response_format=url` dilakukan gateway (TASK-14).

### Generate (image-to-image, `/v1/images/edits`)
Body JSON runtime = body text-to-image + `"image": "<base64 PNG/JPEG>"` + `"strength": 0.0–1.0`
(default `cfg.default_strength`). Gateway (TASK-14) menerjemahkan multipart OpenAI
`/v1/images/edits` ke format ini.
- Gambar didekode, dikonversi RGB, di-resize ke ukuran pipeline → `ov.Tensor` uint8 `[1, H, W, 3]`.
  Batas ukuran file 10 MB.
- `i2i.generate(prompt, image, strength=..., ...)`; langkah efektif = `steps × strength`.
- `mask` (inpainting) tidak didukung di v1 → 400 `unsupported_parameter`.

### Umum
- **Cancel:** `callback(step, num_steps, latent)` mengembalikan `True` bila `cancel` diset →
  generasi berhenti dalam ≤ 1 step, error `cancelled`.
- `safety_checker` tidak tersedia di pipeline GenAI; v1 tanpa safety checker (model base).
- Batas: `steps ≤ cfg.max_steps`; prompt dipotong ke 77 token CLIP, dilaporkan di
  `x_runtime.warnings`.
- Varian INT8 (`sd15-int8`) vs FP16: pilih yang lebih cepat dengan kualitas visual wajar;
  keputusan di `docs/hardware.md`.

## Integrasi
- Didaftarkan di `runtime/backends/__init__.py` (`openvino_diffusion`).
- Model NPU pinned (`sd-1.5`, `qwen2.5-coder-1.5b`) di-warmup saat runtime start. Runtime `ready`
  menunggu compile selesai; start pertama tanpa cache bisa beberapa menit, jadi `start-all.bat`
  diberi timeout panjang (TASK-21).
- Device Manager NPU memakai budget `NPU_TOTAL_MB - NPU_RESERVE_MB`.

## Deliverables
- [x] `ov_diffusion_backend.py` (text-to-image + image-to-image, satu set model)
- [x] Validator config device (tolak `AUTO`/`CPU`) — `runtime/backends/ov_common.py`
- [x] Event `compile` (`cache_hit`) dicatat Device Manager bila backend melaporkan `compile_ms`
- [x] Unit test dengan `openvino_genai` palsu (`tests/unit/runtime/test_ov_diffusion.py`)
- [x] Test hardware `@pytest.mark.npu` (`tests/hardware/test_sd_npu.py`, `pytest --hardware`):
      deterministik 25 step, image-to-image, cancel, compile dari cache — lulus di NPU nyata
- [x] Pembaruan `docs/hardware.md` (FP16 vs INT8, compile dengan/tanpa cache, kombinasi device)

## Acceptance Criteria
1. SD v1.5 512×512, 25 step, text-to-image dan image-to-image berjalan di `NPU` (atau kombinasi
   NPU/GPU terdokumentasi), tanpa CPU.
2. Seed & parameter sama → gambar identik (sha256 sama).
3. Restart runtime → compile memakai cache (event `compile` dengan `cache_hit=true`, durasi jauh
   lebih singkat).
4. Image-to-image mempertahankan komposisi gambar input (uji visual) dan menolak request tanpa `image`.
5. Cancel selama generate menghentikan proses dalam ≤ 1 step.
6. Selama SD berjalan di NPU, model Qwen di GPU tetap dapat melayani request (device berbeda,
   thread pool terpisah).
