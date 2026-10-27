# TASK-12 — Runtime Backend OpenVINO: Stable Diffusion v1.5 & Embedding di NPU

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 2 hari |
| Dependensi | TASK-09, TASK-10 |
| Referensi PRD | §7.4 A#2 & C, §8.4, §9.4 |

## Tujuan
Menjalankan **Stable Diffusion v1.5** (text-to-image) dan **bge-m3** (embedding) dengan `openvino` + `optimum[openvino]` di **NPU**, tanpa jatuh ke CPU, dengan cache kompilasi dan antrean yang aman.

## A. `runtime/backends/ov_diffusion_backend.py` (`kind="openvino_diffusion"`)

### Load
```python
pipe = OVStableDiffusionPipeline.from_pretrained(
    spec.artifact_path, compile=False,
    ov_config={"CACHE_DIR": OV_CACHE_DIR, "PERFORMANCE_HINT": "LATENCY"})
pipe.reshape(batch_size=1, height=H, width=W, num_images_per_prompt=1)   # shape statis NPU
apply_component_devices(pipe, cfg.component_devices)   # default semua "NPU"
pipe.compile()
```
- Device **eksplisit** (`"NPU"`, atau `"GPU"` per komponen bila dikonfigurasi). Nilai `"AUTO"`/`"CPU"` ditolak validator config kecuali `ALLOW_CPU_FALLBACK=true`.
- `actual_device()`: baca `compiled_model.get_property("EXECUTION_DEVICES")` per komponen. Bila ada `CPU` → tolak (PRD §7.5 aturan 5).
- Scheduler dari `cfg.scheduler` (default `EulerDiscreteScheduler`; alternatif `DPMSolverMultistepScheduler` untuk step lebih sedikit).
- Satu pipeline per ukuran di `allowed_sizes` (v1: hanya `512x512`). Setiap ukuran tambahan menambah memori dan waktu compile, jadi dihitung ke `vram_mb`.
- Catat `runtime_events(event='compile', duration_ms, details={"cache_hit": bool})`.

### Generate
Request runtime (sudah divalidasi gateway, divalidasi ulang di runtime):
```json
{"model":"sd15", "prompt":"...", "negative_prompt":"...", "n":1, "size":"512x512",
 "steps":25, "guidance_scale":7.5, "seed":42, "response_format":"b64_json"}
```
- Eksekusi di thread device NPU dengan `Semaphore(1)` per pipeline.
- `n` gambar dibuat berurutan dengan `seed + i`. Seed acak (dicatat) bila tidak dikirim. Bentuk generator (numpy `RandomState` atau `torch.Generator`) mengikuti versi optimum yang ter-pin; hasilnya harus deterministik untuk seed yang sama.
- **Cancel:** callback per step (`callback_on_step_end` atau ekuivalen di versi yang dipakai) memeriksa `cancel`; bila diset → hentikan dan kembalikan error `cancelled`.
- Output: PNG (Pillow) di memori → `b64` + `sha256` + `bytes` + metadata (`seed`, `steps`, `guidance_scale`, `width`, `height`, `infer_ms`). Penyimpanan file untuk `response_format=url` dilakukan gateway (TASK-14), bukan runtime.
- `safety_checker` default `None` (model base). Bila caller meminta `safety_checker=true` dan komponen tersedia, aktifkan dan kembalikan flag `nsfw_detected` per gambar di `x_runtime`.
- Batas: `steps ≤ cfg.max_steps`, panjang prompt dipotong ke 77 token CLIP. Pemotongan dilaporkan di `x_runtime.warnings`.

### Opsi kinerja (dievaluasi di TASK-20)
- Varian INT8 (`sd15-int8`) vs FP16: pilih yang lebih cepat dengan kualitas visual masih wajar. Simpan keputusan di `docs/hardware.md`.
- Bila VAE decoder tidak stabil di NPU dan GPU Intel tersedia → `component_devices.vae_decoder="GPU"` (dihitung ke budget GPU di Device Manager).

## B. `runtime/backends/ov_embedding_backend.py` (`kind="openvino_embedding"`)

### Load
```python
model = OVModelForFeatureExtraction.from_pretrained(path, device="NPU", compile=False,
                                                    ov_config={"CACHE_DIR": OV_CACHE_DIR})
model.reshape(cfg.static_batch, cfg.max_seq_len)   # mis. 8 × 512 (NPU butuh shape statis)
model.compile()
tokenizer = AutoTokenizer.from_pretrained(path)
```

### Embed
- Input dipotong per batch `static_batch`. Batch terakhir di-pad dengan string kosong lalu dibuang dari hasil.
- Tokenisasi dengan `padding="max_length", truncation=True, max_length=cfg.max_seq_len`. Input yang terpotong dilaporkan di `x_runtime.truncated_inputs`.
- Pooling sesuai `cfg.pooling` (`cls` untuk bge-m3), lalu normalisasi L2 bila `cfg.normalize`.
- `dimensions` dari caller: tolak (400) bila ≠ 1024 untuk bge-m3.
- Usage `prompt_tokens` = jumlah token non-padding (akurat dari tokenizer).

## C. Integrasi
- Kedua backend didaftarkan di `runtime/backends/__init__.py` mapping `kind → class`.
- Model NPU pinned (`sd-1.5`, `bge-m3`) di-warmup saat runtime start. Runtime `ready` menunggu keduanya selesai compile. Start pertama tanpa cache bisa beberapa menit, jadi `start-all.bat` diberi timeout panjang (TASK-21).
- Device Manager NPU memakai budget `NPU_TOTAL_MB - NPU_RESERVE_MB`.

## Deliverables
- [ ] `ov_diffusion_backend.py`, `ov_embedding_backend.py`
- [ ] Validator config device (tolak `AUTO`/`CPU`)
- [ ] Test hardware `@pytest.mark.npu`: generate deterministik (seed sama → sha256 sama), cancel, embedding batch ganjil (mis. 13 input)
- [ ] Pembaruan `docs/hardware.md` (FP16 vs INT8, waktu compile dengan/tanpa cache, kombinasi device komponen)

## Acceptance Criteria
1. SD v1.5 512×512, 25 step, berjalan dengan `EXECUTION_DEVICES` = `NPU` (atau kombinasi NPU/GPU yang terdokumentasi), tanpa CPU.
2. Seed & parameter sama → gambar identik (sha256 sama).
3. Restart runtime → compile memakai cache (event `compile` dengan `cache_hit=true`, durasi jauh lebih singkat).
4. bge-m3 di NPU: 13 input menghasilkan 13 vektor berdimensi 1024 dan ternormalisasi; kemiripan kosinus kalimat ID–EN yang setara > kalimat tidak terkait.
5. Cancel selama generate menghentikan proses dalam ≤ 1 step.
6. Selama SD berjalan, model GGUF di GPU tetap dapat melayani request (device berbeda, thread pool terpisah).
