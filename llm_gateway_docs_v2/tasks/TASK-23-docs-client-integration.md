# TASK-23 — Dokumentasi & Panduan Integrasi Klien

| Item | Nilai |
|---|---|
| Milestone | M6 Kualitas & Rilis |
| Prioritas | P1 |
| Estimasi | 1 hari |
| Dependensi | TASK-09, TASK-14, TASK-17, TASK-20, TASK-21, TASK-22 |
| Referensi PRD | §16, §19 |

## Tujuan
Membuat project lain bisa memakai gateway dalam < 10 menit, dan admin bisa mengoperasikannya tanpa membuka kode.

## Isi Dokumentasi

### `README.md`
- Ringkasan, arsitektur singkat, prasyarat portable (PostgreSQL, conda env Python 3.10–3.12, Git, Traefik opsional), prasyarat hardware (GPU 8 GB + driver, NPU Intel + driver), dan ruang disk ≥ 40 GB untuk model.
- Quick start: clone via `git-cmd.exe` → install dependency di Conda Prompt → instal akselerator (TASK-09: wheel GPU `llama-cpp-python`, OpenVINO) → salin `.env.example` → buat DB → `migrate.bat` → `manage.py seed` → `download_models.py` + `convert_openvino.py` → `measure_models.py` → `manage.py seed --update-local` → `manage.py create-admin-key` → `start-all.bat`.
- Tabel script `.bat` dan fungsinya.

### `docs/client-integration.md`
Contoh siap pakai:
1. **Python SDK OpenAI** (non-stream, stream, tools, embeddings, **images** (`client.images.generate`), **vision** (`image_url`), **FIM** via `client.completions.create(prompt=..., suffix=...)`, header `X-Caller-Task`).
2. **JavaScript/TypeScript SDK OpenAI** (`baseURL`).
3. **httpx / curl** mentah (untuk debugging SSE).
4. **LangChain** (`ChatOpenAI(base_url=..., api_key=..., model="smart")`), **LlamaIndex** (`OpenAILike`), **CrewAI/AutoGen** (konfigurasi OpenAI-compatible).
5. **Coding assistant**: Continue, Cline, Aider, Open WebUI — langkah konfigurasi "OpenAI compatible provider", route `autocomplete` (Qwen2.5-Coder-1.5B, FIM) untuk tab-autocomplete, `code` (Qwen2.5-Coder-7B) untuk chat/agent kode, dan `smart` untuk task berat. Sertakan contoh config Continue (model chat + `tabAutocompleteModel`) dengan kolom aktual yang diverifikasi terhadap versi Continue terbaru.
6. **Cursor**: cara override base URL + catatan bahwa sebagian request Cursor diproses melalui server Cursor sehingga `localhost` bisa tidak terjangkau; verifikasi perilaku versi terbaru dan opsi tunnel bila perlu.
7. Pola agent: gateway tidak menyuntikkan system prompt — contoh mengirim persona/aturan dari sisi project.
8. Penanganan error & retry di sisi klien (429 `Retry-After`, 502/504), memakai `X-Request-ID` untuk penelusuran ke admin.

### `docs/model-catalog.md`
- Tabel 11 model lokal (PRD §7.4): alias, sumber repo + file + sha256, kuantisasi, device, `vram_mb` **terukur**, `n_ctx`, kapabilitas, **lisensi** (dan batasan pemakaian, mis. Llama Community License, CreativeML OpenRAIL-M), serta kegunaan yang disarankan.
- Tabel route default (PRD §9.5) dan kapan memakai masing-masing.
- **Panduan memilih model untuk project**: ringan vs berat, lokal vs remote, dampak swap GPU (hindari bolak-balik antar model 7–8B dalam satu alur agent; pilih satu model heavy per alur, atau pakai route `prefer_loaded`).
- **Cara menambah model lokal baru**: unduh GGUF / konversi OpenVINO → ukur `vram_mb` (`measure_models.py`) → `POST /admin/models` → reload. Disertai checklist budget §7.5.
- Cara menambah provider/model/route remote via Admin API, arti `tier`, kapabilitas, dan harga per 1 juta token.
- Pengingat: cek nama model & harga terbaru di dokumentasi resmi masing-masing provider, lalu update via Admin API (tanpa ubah kode).

### `docs/database.md`
- ERD (salin dari PRD §9.1) + penjelasan setiap tabel & kolom.
- Query siap pakai:
  - biaya per project bulan ini,
  - top 10 request paling lambat 24 jam terakhir,
  - tingkat error per provider per hari,
  - penelusuran satu `caller_task`.

### `docs/operations.md` (lanjutan TASK-19)
- Start/stop, lokasi log, membaca log JSON (`findstr` / `jq` bila tersedia dari Git portable), rotasi key provider (ubah `.env` → restart gateway), revoke key client, backup/restore, troubleshooting umum:
  - DLL load failed → jalankan via `env.bat`,
  - port terpakai → `netstat -ano | findstr :8000`,
  - model lokal lambat → cek `X-Gateway-Device` dan log runtime (semua layer offloaded?), turunkan `n_ctx`, cek swap berlebihan di `/admin/runtime/swap-stats`,
  - `llama_supports_gpu_offload()=False` → wheel CPU terpasang; instal ulang dari index CUDA/Vulkan (TASK-09),
  - NPU tidak muncul di `available_devices` → driver NPU,
  - compile NPU lama setiap start → cek `OV_CACHE_DIR` dapat ditulis dan versi OpenVINO tidak berubah,
  - OOM GPU → lihat `runtime_events` (`oom`), periksa `vram_mb` dan total pinned,
  - runtime restart berulang → `logs/runtime-supervisor.log` & `runtime-error.log`,
  - stream tertahan di Traefik → cek middleware buffering.

### `docs/hardware.md` & `docs/perf-report.md`
Dari TASK-09 dan TASK-20: hasil probe, backend yang dipilih, tabel VRAM, dan benchmark.

### `docs/admin-api.http`
Koleksi request untuk seluruh endpoint admin (dari TASK-17).

### `CHANGELOG.md`
Mulai dari `0.1.0`.

## Deliverables
- [ ] Semua dokumen di atas
- [ ] Contoh kode dieksekusi sekali terhadap gateway berjalan (bukan sekadar ditulis)

## Acceptance Criteria
1. Orang lain (atau project baru) berhasil memanggil gateway hanya dengan mengikuti `docs/client-integration.md`, termasuk contoh image, vision, dan FIM.
1b. Setup model lokal dari nol dapat diulang hanya dengan mengikuti README + `docs/model-catalog.md`.
2. Setiap contoh kode di dokumentasi lulus dijalankan.
3. Admin dapat membuat project + key + kuota hanya dengan `docs/admin-api.http`.
