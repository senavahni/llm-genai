# TASK-10 — Local Runtime: Proses Terpisah, Device Manager & Adapter Gateway

| Item | Nilai |
|---|---|
| Milestone | M3 Local Runtime |
| Prioritas | P0 |
| Estimasi | 3 hari |
| Dependensi | TASK-03, TASK-04, TASK-06, TASK-09 |
| Referensi PRD | §5.3 (6–8), §7.1, §7.5, §10.5, §12 |

## Tujuan
Membangun proses **Local Runtime** (FastAPI, `127.0.0.1:8100`) yang memuat dan menjalankan model lokal di GPU/NPU dengan manajemen memori ketat, plus adapter `local_runtime_provider` di gateway.

## Spesifikasi

### 1. Kerangka runtime (`runtime/`)
- `runtime/main.py`: `create_runtime_app()` dengan lifespan sebagai berikut.
  1. `setup_logging` → `logs/runtime.log`, `logs/runtime-error.log` (memakai ulang `app/utils/logger.py` dengan nama file berbeda).
  2. `probe.detect()` → bila GPU/NPU yang dibutuhkan model enabled tidak ada **dan** `ALLOW_CPU_FALLBACK=false` → gagal start dengan pesan jelas. Catat `runtime_events(event='device_error')`.
  3. `catalog.load()` dari tabel `models` (`device <> 'remote' AND is_enabled`).
  4. `DeviceManager` dibuat per device (`gpu`, `npu`) dengan budget dari env.
  5. Warmup model `is_pinned` di background task. `ready=false` sampai semua pinned termuat.
  6. Catat `runtime_events(event='runtime_start')`. Saat shutdown: unload semua dan catat `runtime_stop`.
- Layering: `routes/` → `controllers/` → `services/inference_service.py` → `device/manager.py` → `backends/*`.
- Auth: dependency yang memeriksa header `X-Runtime-Token` == `RUNTIME_TOKEN` (`hmac.compare_digest`). Bind **hanya** `127.0.0.1`.
- `scripts/run_runtime.py` memanggil `uvicorn.run("runtime.main:app", host="127.0.0.1", port=8100, workers=1, log_config=None)`.

### 2. Kontrak backend (`runtime/backends/base.py`)
```python
class LocalBackend(ABC):
    kind: ClassVar[str]                       # llama_cpp_python | llama_server | openvino_diffusion | openvino_embedding
    device: str                               # gpu | npu
    def __init__(self, spec: LocalModelSpec): ...
    async def load(self) -> LoadResult: ...    # dijalankan di thread; kembalikan load_ms, device aktual
    async def unload(self) -> None: ...
    def is_loaded(self) -> bool: ...
    def actual_device(self) -> str: ...        # verifikasi device setelah load (anti-CPU)
    # kapabilitas opsional; default raise CapabilityNotSupported
    async def chat(self, req) -> dict
    def chat_stream(self, req, cancel: asyncio.Event) -> AsyncIterator[dict]
    async def completion(self, req) -> dict
    def completion_stream(self, req, cancel) -> AsyncIterator[dict]
    async def embed(self, inputs: list[str], **kw) -> EmbedResult
    async def generate_images(self, req, cancel) -> list[ImageResult]
```
`LocalModelSpec` dibangun dari baris `models`: `alias`, `upstream_name`, `artifact_path`, `artifact_sha256`, `device`, `runtime_backend`, `vram_mb`, `is_pinned`, `config`.

### 3. Device Manager (`runtime/device/manager.py`)
```python
class DeviceManager:
    def __init__(self, device: str, budget_mb: int, min_residency_s: int, queue_timeout_s: int): ...
    async def acquire(self, spec, request_id) -> Lease      # async context manager
    async def load(self, spec, reason) / unload(alias, reason)
    def status(self) -> DeviceStatus
```
**`acquire()`** (dipakai setiap inferensi):
1. Jika model sudah termuat → ambil `Semaphore(replicas)` model, tunggu dengan `queue_timeout_s`. Habis waktu → `ModelBusy` (503, retryable) dan catat `queue_timeout`.
2. Jika belum termuat → `async with device_lock` (satu load per device):
   - Hitung `free = budget - Σ vram_mb(loaded)`.
   - Bila `spec.vram_mb > budget` → error konfigurasi (`load_failed`).
   - Selama `free < spec.vram_mb`: pilih korban = model **tidak pinned**, **in_flight == 0**, `loaded_at + min_residency` sudah lewat, urut `last_used` terlama → `unload(reason=f"lru_evict_for:{alias}")`. Bila tidak ada korban → tunggu event "model idle" sampai `queue_timeout_s`, lalu `ModelBusy`.
   - `load()` → catat `runtime_events(load, duration_ms, vram_used_mb)`.
3. `Lease` menaikkan `in_flight`, mencatat `queue_ms`/`load_ms`, memperbarui `last_used` saat dilepas, lalu memicu event idle.

**Penanganan OOM saat load:** tangkap exception alokasi (pesan llama.cpp/OpenVINO mengandung `out of memory`, `failed to allocate`, `ErrorCode -5`/`CL_OUT_OF_RESOURCES`, dsb. — pola dikonfigurasi). Lalu:
1. unload dan catat `oom`;
2. bila `config.auto_reduce_ctx`, coba `ctx_fallback` berikutnya;
3. bila tetap gagal → `DeviceOOM` (503, retryable).

**Larangan CPU:** setelah `load()`, panggil `backend.actual_device()`. Bila hasilnya `cpu` dan `ALLOW_CPU_FALLBACK=false` → unload, catat `load_failed(reason='cpu_not_allowed')`, lalu raise `DeviceUnavailable`.

**Pin/unpin runtime:** `POST /runtime/models/{name}/load` dengan `?pin=true` menandai pinned di memori (perubahan permanen lewat Admin API → DB → `catalog/reload`).

Semua penulisan `runtime_events` lewat `event_service.record()` (async, session DB baru, tidak memblokir inferensi; gagal tulis → fallback ke `logs/runtime_events_fallback.jsonl`).

### 4. Eksekusi non-blocking
- Panggilan native (llama-cpp-python, OpenVINO) dijalankan di **thread pool khusus per device** (`ThreadPoolExecutor(max_workers=Σ replicas)`), bukan default executor.
- Streaming: generator native di thread → `asyncio.Queue` via `loop.call_soon_threadsafe` → async generator. `cancel: asyncio.Event` diperiksa di thread setiap token/step.
- Client (gateway) disconnect → runtime mendeteksi lewat `request.is_disconnected()` → set `cancel`.

### 5. Endpoint runtime
Sesuai PRD §10.5. Respons OpenAI-compatible ditambah `x_runtime: {"device":"gpu","load_ms":0,"queue_ms":12,"infer_ms":840,"backend":"llama_cpp_python"}`. Untuk stream, `x_runtime` dikirim pada chunk terakhir. Error memakai format `{"error":{...,"code":"model_busy"|"device_oom"|"device_unavailable"|"capability_not_supported"}}` dengan HTTP status sesuai.

### 6. Adapter gateway (`app/services/providers/local_runtime_provider.py`)
- Satu kelas dipakai untuk provider `llamacpp` dan `openvino` (`code` dari DB).
- Turunan `OpenAIProvider` (TASK-07) dengan `base_url=RUNTIME_URL` dan header `X-Runtime-Token` serta `X-Request-ID`.
- Menambah method `generate_images()` (POST `/v1/images/generations`).
- Mapping error runtime: `model_busy`/`device_oom`/`device_unavailable` → `UpstreamError` **retryable** (agar route fallback); `capability_not_supported` → `CapabilityNotSupported`.
- Membaca `x_runtime` → `UnifiedResponse.runtime_meta` (device, load_ms, queue_ms) untuk dicatat di `requests` (TASK-15).
- Timeout chunk pertama memakai `LOCAL_FIRST_TOKEN_TIMEOUT_S` (default 120 detik) karena mencakup waktu swap.
- `health()` → `GET /health/ready` runtime.

### 7. Supervisor sederhana
`scripts/start-runtime.bat` menjalankan runtime dalam loop: bila proses keluar dengan kode ≠ 0 (crash native/OOM driver), tunggu 5 detik lalu start ulang (maks 5x per 10 menit). Setiap restart ditulis ke `logs/runtime-supervisor.log`.
```bat
@echo off
call "%~dp0env.bat"
set /a N=0
:loop
"%PY%" scripts\run_runtime.py
if %ERRORLEVEL%==0 goto :eof
set /a N+=1
echo %date% %time% runtime exit %ERRORLEVEL% restart #%N%>>"%PROJECT_ROOT%\logs\runtime-supervisor.log"
if %N% GEQ 5 goto :eof
timeout /t 5 /nobreak >nul
goto loop
```

## Deliverables
- [ ] Package `runtime/` (main, core, device, backends/base, services, controllers, routes)
- [ ] `DeviceManager` + `event_service`
- [ ] `app/services/providers/local_runtime_provider.py`
- [ ] `scripts/run_runtime.py`, `scripts/start-runtime.bat`
- [ ] Fake backend (`tests/fakes/fake_backend.py`) dengan `vram_mb`, delay load, dan simulasi OOM
- [ ] Unit test DeviceManager (tanpa hardware)

## Acceptance Criteria
1. Dengan fake backend (budget 7200, pinned 1300, model A 5400, B 5600): request A lalu B → A di-evict (setelah min residency), B dimuat, dan tercatat 1 `evict` + 1 `load`. Pinned tidak pernah di-evict.
2. B diminta saat A sedang melayani request → B menunggu; bila melebihi `queue_timeout` → 503 `model_busy`, dan gateway fallback ke kandidat route berikutnya.
3. Simulasi OOM → `ctx_fallback` dicoba, event `oom` tercatat, tanpa crash proses.
4. `ALLOW_CPU_FALLBACK=false` + backend melapor `cpu` → load ditolak.
5. Runtime yang di-kill paksa → supervisor menyalakan ulang; gateway `/health/ready` menunjukkan `degraded` selama runtime mati.
6. Port 8100 tidak dapat diakses dari luar mesin; request tanpa `X-Runtime-Token` → 401.
7. Saat inferensi berjalan, `GET /runtime/status` tetap merespons < 50 ms.
