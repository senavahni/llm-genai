# PRD — LLM Gateway

| Item | Nilai |
|---|---|
| Nama produk | `llm_gateway` |
| Versi dokumen | **2.0** |
| Tanggal | 27 Oktober 2026 |
| Pemilik | Fahrul |
| Status | Draft untuk implementasi |
| Stack | Python 3.10–3.12 (conda env `llm-genai`), FastAPI, SQLAlchemy 2 (async) + asyncpg, PostgreSQL portable, Alembic, **llama-cpp-python**, **OpenVINO** + **optimum[openvino]** |

### Riwayat revisi
| Versi | Perubahan |
|---|---|
| 1.0 | Draft awal: gateway multi-provider, DB, deployment Traefik/non-Traefik |
| 2.0 | Model lokal wajib (Qwen2.5-7B, SD v1.5 OpenVINO, Qwen2.5-Coder, Qwen2-VL-2B) dan 5 model llama.cpp tambahan. Akselerasi GPU 8 GB dan NPU 8 GB tanpa inferensi di CPU. Proses **Local Runtime** terpisah dengan Device/VRAM Manager. Endpoint gambar `/v1/images/generations`. FIM untuk autocomplete. Tabel `generated_images` dan `runtime_events`. Penyesuaian config, deployment, risiko, dan milestone. |

---

## 1. Ringkasan

`llm_gateway` adalah **penyedia API LLM lokal** yang menyatukan banyak sumber model ke dalam **satu API yang kompatibel dengan format OpenAI**:

- **Remote provider** (pakai API key milik gateway): OpenAI, Anthropic (Claude), Google Gemini.
- **Local provider**, dilayani oleh proses **Local Runtime** yang berjalan di **GPU dan NPU**, bukan CPU:
  - **llama.cpp** via `llama-cpp-python` (GGUF): model teks, kode, vision, dan embedding.
  - **OpenVINO** via `openvino` + `optimum[openvino]`: Stable Diffusion v1.5 (gambar) dan model embedding Hugging Face, terutama di **NPU**.

Project lain (AI agent, coding assistant ala Cursor, script otomasi) cukup memanggil satu base URL dengan satu API key per project. Gateway menangani autentikasi, routing, normalisasi format, streaming, fallback, pencatatan usage dan biaya, rate limit, kuota, serta logging yang dapat diaudit.

Gateway **tidak menentukan behavior model**. Model diperlakukan sebagai "base": system prompt, persona, tools, dan parameter sampling sepenuhnya ditentukan oleh project pemanggil.

## 2. Latar Belakang & Masalah

1. Setiap project harus mengelola SDK, API key, retry, dan format yang berbeda untuk OpenAI, Claude, Gemini, dan model lokal.
2. Tidak ada pencatatan terpusat tentang siapa memakai model apa, berapa token, berapa biaya, dan kenapa gagal.
3. API key provider tersebar di banyak project, sehingga berisiko bocor.
4. Model lokal tidak punya API standar yang bisa dipakai bersamaan oleh beberapa project.
5. **GPU dan NPU masing-masing hanya 8 GB.** Model 7–8B tidak bisa dimuat bersamaan, jadi perlu manajemen memori perangkat yang eksplisit.
6. Lingkungan kerja terbatas: **Windows tanpa akses admin/root, tanpa Docker**, semua tool portable.

## 3. Tujuan

| ID | Tujuan | Ukuran keberhasilan |
|---|---|---|
| G1 | Satu API terpadu untuk semua provider | Project cukup mengganti `base_url` + `api_key` di SDK OpenAI |
| G2 | Mendukung AI agent | Tool calling, streaming, dan JSON mode berjalan di OpenAI, Claude, Gemini, serta model lokal yang mendukung |
| G3 | Mendukung task ringan & berat | Route alias `fast`, `smart`, `code`, `autocomplete`, `vision`, `image` dengan fallback |
| G4 | Accountable | 100% request tercatat di DB, termasuk perangkat yang melayani, dan setiap load/unload model tercatat |
| G5 | Multi-project & aman | API key per project, hash, scope, kuota, rate limit, audit log admin |
| G6 | Berjalan di lingkungan portable | Seluruh komponen jalan via `.bat` tanpa admin & tanpa Docker |
| **G7** | **Model lokal wajib tersedia** | 4 model wajib + ≥ 4 model llama.cpp tambahan terdaftar, dapat dipanggil, dan lulus smoke test |
| **G8** | **Inferensi tidak jatuh ke CPU** | Semua model lokal jalan di GPU/NPU. Runtime menolak load ke CPU kecuali `ALLOW_CPU_FALLBACK=true`. Perangkat aktual tercatat per request. |
| **G9** | **Hemat memori perangkat** | Tidak ada OOM saat pergantian model. Pemakaian VRAM ≤ budget (7,2 GB GPU, 7,5 GB NPU). |

### Non-goal (v1)
- UI dashboard web (cukup Admin API + query SQL).
- Fine-tuning / training model.
- RAG / vector store (gateway hanya menyediakan endpoint embeddings).
- Prompt management / injeksi system prompt oleh gateway.
- Image editing / inpainting / img2img (v1 hanya text-to-image).
- Billing ke pihak ketiga.

## 4. Pengguna & Use Case

| Persona | Kebutuhan |
|---|---|
| **Project AI Agent** | Chat dengan tools, streaming, retry/fallback, metadata task untuk tracing |
| **Coding assistant (Cursor / Continue / Cline / Aider)** | Endpoint OpenAI-compatible, autocomplete FIM cepat (`autocomplete`), chat/agent kode (`code`) |
| **Project vision** | Kirim gambar + pertanyaan ke `vision` |
| **Project generatif gambar** | `POST /v1/images/generations` ke SD v1.5 |
| **Script batch / pipeline** | Embeddings, completion non-stream, kuota |
| **Admin (Fahrul)** | Kelola project, key, model, route, kuota; lihat usage, biaya, error, status GPU/NPU |

**Contoh use case:**
- UC1: Agent A memanggil `model="smart"` → Claude; jika 5xx/timeout, fallback ke GPT, lalu ke Qwen2.5-7B lokal.
- UC2: Continue/Cline memakai `autocomplete` (Qwen2.5-Coder-1.5B, *pinned* di GPU) untuk FIM, dan `code` (Qwen2.5-Coder-7B) untuk chat kode.
- UC3: Project C mengirim screenshot ke `vision` (Qwen2-VL-2B) untuk dibaca isinya.
- UC4: Project D membuat ilustrasi 512×512 via `image` (SD v1.5 di NPU).
- UC5: Pipeline B memanggil `/v1/embeddings` → bge-m3 OpenVINO di NPU.
- UC6: Admin melihat model mana yang paling sering di-swap di GPU dan mengubah konfigurasi *pinned*.

## 5. Batasan Lingkungan (Constraints)

### 5.1 Software
| Komponen | Lokasi / cara jalan |
|---|---|
| PostgreSQL portable | `D:\Data.Fahrul\Documents\PortableDev\start-postgres.bat` |
| Python (conda env) | `D:\Data.Fahrul\.conda\envs\llm-genai\python.exe`. Instalasi paket via **Conda Prompt**. **Versi Python harus 3.10–3.12** agar wheel prebuilt `llama-cpp-python` tersedia. |
| Git portable | `D:\Data.Fahrul\Documents\PortableDev\Git\git-cmd.exe` |
| OS | Windows, **tanpa admin**, **tanpa Docker** |

### 5.2 Hardware
| Perangkat | Kapasitas | Dipakai untuk | Library |
|---|---|---|---|
| **GPU** | 8 GB | Semua model GGUF (teks, kode, vision, embedding GGUF) | `llama-cpp-python` (backend CUDA bila NVIDIA, Vulkan bila Intel Arc/AMD) |
| **NPU** | 8 GB | Stable Diffusion v1.5, embedding HF | `openvino`, `optimum[openvino]` |
| CPU | — | Orkestrasi, tokenisasi, HTTP. **Bukan untuk inferensi.** | — |

**Asumsi yang perlu dikonfirmasi saat TASK-09:** NPU adalah Intel NPU (Core Ultra), karena OpenVINO hanya mendukung NPU Intel. Vendor GPU (NVIDIA / Intel Arc) menentukan varian wheel `llama-cpp-python`. Device OpenVINO `GPU` hanya tersedia bila GPU-nya Intel.

### 5.3 Implikasi desain
1. **Tidak memakai Redis**: rate limit in-memory + counter di PostgreSQL.
2. **Tidak memakai Windows Service** (butuh admin): proses dijalankan via `.bat`; autostart opsional via Task Scheduler level user.
3. **`uvloop` tidak tersedia di Windows**: pakai event loop asyncio default.
4. **PATH DLL conda** (`envs\llm-genai\Library\bin`) wajib disiapkan oleh `scripts\env.bat`, karena dibutuhkan oleh `llama-cpp-python`, OpenVINO, dan numpy.
5. Port dipakai ≥ 1024: 8000 (gateway), 8100 (runtime), 8080/8081 (Traefik), 8443 (opsional).
6. **Inferensi lokal di proses terpisah (Local Runtime).** Library native bisa crash atau OOM di driver GPU/NPU; isolasi proses menjaga gateway (auth, logging, remote provider) tetap hidup.
7. **Budget memori perangkat ketat.** Model 7–8B (≈5–6 GB VRAM) tidak bisa bersamaan, sehingga dipakai skema *pinned* + *swap slot* + eviction LRU (§7.5).
8. **NPU butuh shape statis**: SD v1.5 dikompilasi untuk 512×512; embedding NPU memakai panjang sekuens tetap (512). Kompilasi NPU lambat, jadi wajib pakai cache (`CACHE_DIR`).

## 6. Ruang Lingkup Fitur

### 6.1 Fungsional (Must Have — v1)

| ID | Fitur | Deskripsi |
|---|---|---|
| F1 | OpenAI-compatible Chat | `POST /v1/chat/completions` (stream & non-stream), tools, `tool_choice`, `response_format`, sampling, image input untuk model vision |
| F2 | Text Completion + **FIM** | `POST /v1/completions` untuk raw prompt; field `suffix` → prompt FIM (Qwen2.5-Coder) untuk autocomplete |
| F3 | Embeddings | `POST /v1/embeddings` (OpenAI, Gemini, bge-m3 OpenVINO/NPU, nomic GGUF/GPU) |
| **F3b** | **Image generation** | `POST /v1/images/generations` (OpenAI-compatible) → SD v1.5 OpenVINO; output `b64_json` atau `url` |
| F4 | Model listing | `GET /v1/models` hanya menampilkan model/route yang diizinkan untuk project pemanggil |
| F5 | Provider adapters | OpenAI, Anthropic, Gemini, **local (llama.cpp & OpenVINO via Local Runtime)** |
| F6 | Routing & fallback | Alias route dengan strategi `priority` / `round_robin`; fallback hanya sebelum token pertama |
| F7 | Auth API key | Key per project, `lgw_<prefix>_<secret>`, hash, scope, expiry, revoke, rotate |
| F8 | Rate limit | RPM & TPM per key |
| F9 | Kuota | Request/token/**gambar**/biaya harian & bulanan per project |
| F10 | Usage & cost accounting | Token, jumlah gambar, biaya per request, agregat harian |
| F11 | Request log & attempts | Setiap request dan attempt tercatat, termasuk **device** yang melayani |
| F12 | Payload logging opsional | Per project, default **off**, dengan retensi |
| F13 | Admin API | CRUD project, key, provider, model, route, kuota; query request, usage, audit |
| F14 | Audit log | Semua aksi admin tercatat (before/after) |
| F15 | Health & metrics | `/health/*`, `/metrics`, termasuk VRAM/NPU usage & model termuat |
| F16 | Caller tracing | `X-Request-ID`, `X-Caller-Task`, `X-Caller-Agent` + `metadata` |
| F17 | Deployment | Mode tanpa Traefik dan dengan Traefik |
| **F18** | **Local Runtime** | Proses terpisah: model loader, Device/VRAM Manager (pinned, LRU eviction, antrean per model), larangan inferensi CPU |
| **F19** | **Runtime admin** | Lihat status perangkat, load/unload/pin model manual, riwayat `runtime_events` |

### 6.2 Should Have (v1.1)
- `POST /v1/messages` kompatibel format Anthropic.
- Cache respons non-stream berbasis hash (opsional per project).
- Ukuran gambar tambahan (512×768, 768×512) sebagai shape statis tambahan di NPU.
- Speculative decoding (Qwen2.5-Coder-1.5B sebagai draft untuk Coder-7B) bila didukung versi llama-cpp-python.

### 6.3 Could Have (v2)
- Dashboard web admin.
- Model teks kecil di NPU via OpenVINO GenAI sebagai cadangan saat GPU penuh.
- img2img / inpainting.
- Multi-instance gateway dengan state rate-limit di PostgreSQL.

## 7. Arsitektur

### 7.1 Diagram Komponen

```
 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
 │ Project Agent │  │ Cursor/IDE   │  │ Batch Script │
 └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
        │  OpenAI-compatible HTTP (Bearer lgw_...)
        ▼                 ▼                 ▼
 ┌─────────────────────────────────────────────────┐
 │        (opsional) Traefik :8080                  │
 └───────────────────────┬─────────────────────────┘
                         ▼
 ┌─────────────────────────────────────────────────┐
 │           llm_gateway (FastAPI, :8000)           │
 │ routes → controllers → services → models         │
 │ utils: logger · auth · streaming · helper        │
 │ providers: openai · anthropic · gemini · local   │
 └───┬────────────┬───────────────────────┬────────┘
     │            │                       │ HTTP 127.0.0.1:8100 (X-Runtime-Token)
     ▼            ▼                       ▼
 PostgreSQL   Remote APIs   ┌──────────────────────────────────────┐
 (:5432)  ◄───────────────┐ │     Local Runtime (FastAPI, :8100)    │
                          │ │  Device Manager (budget, LRU, pin)    │
                          │ │  ┌─────────── GPU 8 GB ───────────┐   │
                          │ │  │ llama-cpp-python (CUDA/Vulkan) │   │
                          │ │  │ Qwen2.5-7B · Coder-7B/1.5B ·   │   │
                          │ │  │ Qwen2-VL-2B · Llama · Phi · ...│   │
                          │ │  └────────────────────────────────┘   │
                          │ │  ┌─────────── NPU 8 GB ───────────┐   │
                          │ │  │ OpenVINO / optimum-intel        │   │
                          │ │  │ SD v1.5 (512²) · bge-m3         │   │
                          │ │  └────────────────────────────────┘   │
                          └─┤  runtime_events → PostgreSQL          │
                            └──────────────────────────────────────┘
```

### 7.2 Pola MVC (Layering)

| Layer | Tanggung jawab | Boleh memanggil |
|---|---|---|
| `routes/` | `APIRouter`, path, dependency (auth, scope), response model. Tipis. | controllers |
| `controllers/` | Orkestrasi per use case, membentuk response/stream | services, schemas |
| `services/` | Logika bisnis: routing, provider, usage, kuota, audit | models, providers, utils |
| `services/providers/` | Adapter ke tiap provider, translasi format | utils, httpx/SDK |
| `models/` | ORM SQLAlchemy | — |
| `schemas/` | Pydantic v2: request/response API dan DTO internal | — |
| `utils/` | `logger`, `helper`, `auth`, `streaming`, `errors`, `crypto`, `metrics` | — |
| `core/` | config, database, lifespan, registry | — |
| `middlewares/` | request context, access log, error handler | utils |

Aturan: route **tidak boleh** mengakses DB langsung; service **tidak boleh** mengembalikan objek FastAPI `Response`.

**Local Runtime** memakai layering yang sama (routes → controllers → services) di package `runtime/`, dan berbagi `app/core/config.py`, `app/core/database.py`, `app/utils/logger.py`, serta `app/models/`.

### 7.3 Struktur Folder

```
llm_gateway/
├── app/                              # GATEWAY
│   ├── main.py
│   ├── core/  (config.py, database.py, lifespan.py, registry.py)
│   ├── utils/ (logger.py, helper.py, auth.py, streaming.py, errors.py, crypto.py, metrics.py)
│   ├── middlewares/ (request_context.py, error_handler.py)
│   ├── models/
│   │   ├── base.py project.py api_key.py provider.py model.py route.py quota.py
│   │   ├── request.py usage.py audit.py
│   │   └── image.py runtime_event.py          # baru
│   ├── schemas/ (openai_compat.py, images.py, unified.py, admin.py, common.py, converters.py)
│   ├── services/
│   │   ├── providers/
│   │   │   ├── base.py openai_provider.py anthropic_provider.py gemini_provider.py
│   │   │   ├── local_runtime_provider.py      # llama.cpp + OpenVINO via Local Runtime
│   │   │   └── translate/ (anthropic_map.py, gemini_map.py)
│   │   ├── router_service.py chat_service.py completion_service.py embedding_service.py
│   │   ├── image_service.py                   # baru
│   │   ├── usage_service.py quota_service.py ratelimit_service.py
│   │   ├── project_service.py key_service.py model_service.py audit_service.py
│   │   └── maintenance_service.py
│   ├── controllers/ (chat, completion, embedding, image, model, usage, admin/*)
│   └── routes/ (v1/*, admin/*, health.py)
├── runtime/                          # LOCAL RUNTIME (proses terpisah)
│   ├── main.py                       # create_runtime_app()
│   ├── core/ (settings.py, lifespan.py, catalog.py)
│   ├── device/
│   │   ├── probe.py                  # deteksi GPU/NPU, VRAM total/free
│   │   └── manager.py                # DeviceManager: budget, pin, LRU, antrean
│   ├── backends/
│   │   ├── base.py                   # LocalBackend (abstract)
│   │   ├── llamacpp_backend.py       # llama-cpp-python (chat, completion/FIM, vision, embed)
│   │   ├── llama_server_backend.py   # cadangan: subprocess llama-server.exe (GPU)
│   │   ├── ov_diffusion_backend.py   # SD v1.5 OpenVINO
│   │   └── ov_embedding_backend.py   # bge-m3 OpenVINO
│   ├── services/ (inference_service.py, event_service.py)
│   ├── controllers/ (inference_controller.py, runtime_controller.py)
│   └── routes/ (v1.py, runtime.py, health.py)
├── migrations/
├── scripts/
│   ├── env.bat start-postgres.bat start-runtime.bat start-gateway.bat start-traefik.bat
│   ├── start-all.bat start-all-traefik.bat stop-all.bat migrate.bat
│   ├── download_models.py convert_openvino.py probe_devices.py
│   ├── run_server.py run_runtime.py wait_port.py healthcheck.py
│   ├── seed_models.yaml
│   └── manage.py
├── deploy/traefik/ (traefik.yml, dynamic.yml)
├── local_models/                     # di-.gitignore
│   ├── gguf/ (*.gguf, mmproj-*.gguf)
│   ├── openvino/ (sd15-fp16/, sd15-int8/, bge-m3-int8/)
│   ├── hf_cache/
│   └── ov_cache/                     # cache kompilasi OpenVINO (NPU/GPU)
├── storage/images/                   # hasil SD (response_format=url), di-.gitignore
├── logs/
├── tests/
├── .env.example alembic.ini requirements.txt requirements-local.txt README.md
```

### 7.4 Katalog Model Lokal

Ukuran dan VRAM adalah **perkiraan** (bobot + KV cache pada `n_ctx` default + compute buffer). Nilai aktual **wajib diukur** di TASK-09 dan disimpan ke `models.vram_mb`.

#### A. Model wajib

| # | Alias gateway | Model | Format / kuantisasi | Device | ≈ Ukuran file | ≈ VRAM | `n_ctx` default | Kapabilitas | Tier |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `local/qwen2.5-7b` | Qwen2.5-7B-Instruct | GGUF Q4_K_M | GPU | 4,7 GB | 5,4 GB | 8192 (KV q8_0) | chat, tools, json | heavy |
| 2 | `local/sd-1.5` | Stable Diffusion v1.5 | OpenVINO IR FP16 (opsi INT8 hybrid) | **NPU** | 2,1 GB | 2,5 GB | 512×512 statis | image | heavy |
| 3a | `local/qwen2.5-coder-7b` | Qwen2.5-Coder-7B-Instruct | GGUF Q4_K_M | GPU | 4,7 GB | 5,6 GB | 12288 (KV q8_0) | chat kode, tools | heavy |
| 3b | `local/qwen2.5-coder-1.5b` | Qwen2.5-Coder-1.5B (base, FIM) | GGUF Q4_K_M | GPU (**pinned**) | 1,0 GB | 1,3 GB | 4096 | completion, **FIM** | light |
| 4 | `local/qwen2-vl-2b` | Qwen2-VL-2B-Instruct + mmproj | GGUF Q4_K_M + mmproj F16/Q8 | GPU | 1,0 + 0,7–1,3 GB | 2,4 GB | 4096 | chat, **vision** | light |

Catatan:
- Kedua varian Coder dipakai: **1.5B** (*pinned*, autocomplete cepat, tidak pernah di-evict) dan **7B** (chat/agent kode, swap). Jika ingin sangat ringan, route `code` cukup diarahkan ke 1.5B-Instruct.
- Vision memakai `MTMDChatHandler` (handler generik mtmd) di `llama-cpp-python`. Bila Qwen2-VL belum didukung versi terpasang, pakai backend cadangan `llama-server.exe --mmproj` di GPU (TASK-11).
- SD v1.5 diambil dari repo `stable-diffusion-v1-5/stable-diffusion-v1-5` (repo `runwayml` sudah tidak tersedia), lalu dikonversi dengan `optimum-cli export openvino`.

#### B. Model tambahan llama.cpp (GGUF, GPU)

| # | Alias gateway | Model | Kuantisasi | ≈ File | ≈ VRAM | `n_ctx` | Kegunaan | Tier |
|---|---|---|---|---|---|---|---|---|
| 5 | `local/llama-3.2-3b` | Llama-3.2-3B-Instruct | Q4_K_M | 2,0 GB | 2,8 GB | 8192 (KV q8_0) | chat cepat, tools ringan → route `fast` | light |
| 6 | `local/llama-3.1-8b` | Llama-3.1-8B-Instruct | Q4_K_M | 4,9 GB | 5,8 GB | 8192 (KV q8_0) | chat umum, tools, bahasa Inggris kuat | heavy |
| 7 | `local/phi-3.5-mini` | Phi-3.5-mini-instruct | Q4_K_M | 2,4 GB | 3,4 GB | 4096 (KV q8_0) | reasoning ringan, ringkasan | light |
| 8 | `local/deepseek-r1-qwen-7b` | DeepSeek-R1-Distill-Qwen-7B | Q4_K_M | 4,7 GB | 5,4 GB | 8192 (KV q8_0) | reasoning bertahap (output `<think>`) → route `reason` | heavy |
| 9 | `local/nomic-embed` | nomic-embed-text-v1.5 | F16 | 0,27 GB | 0,4 GB | 2048 | embedding di GPU (cadangan bge-m3 NPU) | light |

#### C. Model pendukung OpenVINO (NPU)

| Alias | Model | Format | Device | ≈ Memori | Kegunaan |
|---|---|---|---|---|---|
| `local/bge-m3` | BAAI/bge-m3 | OpenVINO IR INT8, seq 512 statis | NPU (**pinned**) | 0,7 GB | embedding default (multibahasa, cocok untuk Indonesia) |

Semua lisensi model (Llama Community License, Qwen, CreativeML OpenRAIL-M untuk SD, MIT untuk Phi/DeepSeek-distill, dsb.) wajib dicek dan dicatat di `docs/model-catalog.md` sebelum dipakai di project lain.

### 7.5 Alokasi Perangkat & Device Manager

**Budget:**

| Device | Total | Cadangan (driver, context, fragmentasi) | **Budget runtime** |
|---|---|---|---|
| GPU | 8192 MB | 1000 MB | **7200 MB** |
| NPU | 8192 MB | 700 MB | **7500 MB** |

**Layout default GPU (7200 MB):**
```
┌─ pinned ─────────────────────┬─ swap area (≈5900 MB) ───────────────────────────┐
│ qwen2.5-coder-1.5b  1300 MB  │ salah satu: qwen2.5-7b 5400 │ coder-7b 5600 │      │
│                              │ llama-3.1-8b 5800 │ deepseek-r1-7b 5400           │
│                              │ ATAU kombinasi kecil: llama-3.2-3b 2800 +         │
│                              │ qwen2-vl-2b 2400 (+ nomic 400)                    │
└──────────────────────────────┴───────────────────────────────────────────────────┘
```
**Layout default NPU (7500 MB):** `sd-1.5` 2500 MB (pinned) + `bge-m3` 700 MB (pinned). Sisa ruang dicadangkan untuk shape tambahan SD (v1.1) atau model OpenVINO lain.

**Aturan Device Manager:**
1. Setiap model punya `device`, `vram_mb` (hasil ukur), `is_pinned`.
2. Saat request untuk model yang belum termuat:
   1. Jika `vram_mb` ≤ sisa budget → load.
   2. Jika tidak → pilih korban eviction: model **tidak pinned**, **tidak sedang melayani request**, urut LRU. Unload sampai cukup.
   3. Jika semua kandidat korban sedang sibuk → request menunggu di antrean (maks `RUNTIME_QUEUE_TIMEOUT`, default 30 detik), lalu `503 model_busy` (*retryable*) sehingga gateway fallback ke kandidat route berikutnya, misalnya remote provider.
3. **Anti-thrashing:** model yang baru dimuat punya *minimum residency* 60 detik. Swap dibatasi maksimal 1 proses load bersamaan per device (`asyncio.Lock` per device).
4. **Antrean per model:** satu instans `Llama` melayani satu generasi pada satu waktu (`Semaphore(1)`). Model *pinned* kecil boleh punya `replicas: 2` bila budget mengizinkan.
5. **Larangan CPU:**
   - GGUF dimuat dengan `n_gpu_layers=-1` (seluruh layer ke GPU). Load ditolak bila `llama_supports_gpu_offload()` = false.
   - OpenVINO memakai device eksplisit `"NPU"` atau `"GPU"`, **tidak pernah** `"AUTO"`/`"CPU"`.
   - Runtime gagal start dengan pesan jelas bila GPU/NPU tidak terdeteksi, kecuali `ALLOW_CPU_FALLBACK=true` (hanya untuk dev). Bila diaktifkan, device `cpu` tercatat di DB.
6. **OOM handling:** error alokasi saat load → unload model, catat `runtime_events(event='oom')`, turunkan `n_ctx` satu tingkat bila `config.auto_reduce_ctx=true`, lalu coba sekali lagi. Jika tetap gagal → error *retryable* ke gateway.
7. **Warmup:** model pinned dimuat saat runtime start. Kompilasi NPU memakai `CACHE_DIR=local_models/ov_cache`; start pertama bisa beberapa menit, start berikutnya hanya beberapa detik.
8. Setiap load, unload, evict, OOM, compile, dan error device dicatat di tabel `runtime_events`.

## 8. Alur Request

### 8.1 Chat completion (non-stream)
1. Middleware membuat/menerima `X-Request-ID`, mencatat waktu mulai, mengikat context log.
2. `auth.require_scope("chat")` → lookup key via prefix (cache 60 detik), verifikasi hash, cek status/expiry/project.
3. `ratelimit_service.check(key)`.
4. `quota_service.check(project)`.
5. `router_service.resolve(model, project)` → kandidat terurut, dengan filter izin dan kapabilitas.
6. `usage_service.start_request(...)` → insert `requests` status `pending`.
7. `chat_service.execute()` mencoba kandidat berurutan dan mencatat setiap attempt. Error yang boleh fallback: timeout, koneksi, 429, 5xx, `model_busy`, `device_oom`. Error validasi 4xx tidak di-fallback.
8. Response dinormalisasi ke format OpenAI, dengan header `X-Request-ID`, `X-Gateway-Provider`, `X-Gateway-Model`, `X-Gateway-Device`, `X-Gateway-Attempts`.
9. `usage_service.finish_request(...)` dijalankan sebagai background task.

### 8.2 Chat completion (stream)
- SSE: `data: {chunk}\n\n` … `data: [DONE]\n\n`, dengan header `Cache-Control: no-cache` dan `X-Accel-Buffering: no`.
- Fallback hanya **sebelum chunk pertama**. Untuk model lokal, waktu load/swap termasuk dalam masa tunggu chunk pertama. Timeout chunk pertama lokal default 120 detik (lebih panjang dari remote) agar swap model 7B sempat selesai.
- Usage diambil dari event akhir provider, atau diestimasi (`usage_estimated=true`).
- Client disconnect → upstream dibatalkan. Untuk lokal, runtime menghentikan generasi lewat stopping criteria. Status dicatat `cancelled`.
- `ttft_ms` dicatat. Untuk lokal, `load_ms` (waktu load/swap bila terjadi) juga dicatat di `tags`.

### 8.3 Completion FIM (autocomplete)
- `POST /v1/completions` dengan `prompt` (prefix) + `suffix`.
- Jika model `supports_fim=true`, runtime menyusun prompt sesuai template model (`models.config.fim_template`). Contoh Qwen2.5-Coder: `<|fim_prefix|>{prompt}<|fim_suffix|>{suffix}<|fim_middle|>`.
- Default `max_tokens` FIM 128 dan stop token FIM ditambahkan otomatis oleh runtime. Ini konfigurasi teknis template, bukan behavior.

### 8.4 Image generation
1. Auth scope `images`, rate limit, kuota (`max_images`).
2. Resolve `model` (`image` → `local/sd-1.5`, opsional fallback ke model gambar remote yang didaftarkan).
3. Validasi: `size` ∈ `models.config.allowed_sizes` (default `["512x512"]`), `n` ≤ 4, `steps` ≤ 50 (default 25), `guidance_scale` 1–15 (default 7.5).
4. Runtime menjalankan pipeline OpenVINO di NPU dalam thread. Antrean `Semaphore(1)` per pipeline. `n` gambar dibuat berurutan dengan seed `seed + i`.
5. `response_format`:
   - `b64_json` (default): PNG base64 di respons.
   - `url`: file disimpan di `storage/images/{yyyy-mm-dd}/{request_id}_{i}.png`, dicatat di `generated_images`, dan diakses via `GET /v1/images/files/{image_id}`. Akses memerlukan API key project yang sama; file kedaluwarsa sesuai retensi.
6. Usage: `image_count = n`, `cost_usd = n × cost_per_image` (0 untuk lokal kecuali diisi).

### 8.5 Pemetaan format per provider

| Aspek | OpenAI | Anthropic | Gemini | Local llama.cpp (llama-cpp-python) | Local OpenVINO |
|---|---|---|---|---|---|
| System prompt | message `system` | param `system` | `system_instruction` | chat template GGUF | — |
| Tools | native | `tool_use`/`tool_result` | `function_declarations` | `chat_format="chatml-function-calling"` atau template GGUF (Jinja). Hanya model `supports_tools`. | tidak |
| Vision | `image_url` | block image | `inline_data` | `MTMDChatHandler` + mmproj (`image_url` data URL/http) | tidak |
| `max_tokens` | opsional | **wajib** | `max_output_tokens` | `max_tokens` | — |
| Stream | SSE | SSE typed | SSE | `create_chat_completion(stream=True)` di thread → SSE runtime | — |
| Embedding | native | — | `embed_content` | `Llama(embedding=True).create_embedding` | `OVModelForFeatureExtraction` + pooling |
| Gambar | (opsional) | — | — | — | `OVStableDiffusionPipeline` |

Field ekstensi `extra_body.provider_options` diteruskan apa adanya ke provider (mis. `thinking` Claude, `top_k`/`min_p`/`repeat_penalty` llama.cpp, `negative_prompt` SD).

## 9. Desain Database

PostgreSQL ≥ 14, database `llm_gateway`, schema `public`, migrasi via Alembic. Enum memakai `VARCHAR + CHECK`. Semua waktu `TIMESTAMPTZ` (UTC).

### 9.1 ERD (ringkas)

```
projects 1─* api_keys
projects 1─* quotas
projects 1─* project_allowed_models
projects 1─* requests *─1 api_keys
providers 1─* models
model_routes 1─* model_route_targets *─1 models
requests 1─* request_attempts
requests 1─0..1 request_payloads
requests 1─* generated_images          (baru)
models   1─* runtime_events            (baru)
usage_daily  (agregat: day × project × model_alias × provider)
audit_logs   (aksi admin)
```

### 9.2 DDL

```sql
-- =========================== MASTER ===========================
CREATE TABLE projects (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    name                VARCHAR(128) NOT NULL,
    description         TEXT,
    owner               VARCHAR(128),
    status              VARCHAR(16)  NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','suspended','archived')),
    log_payloads        BOOLEAN      NOT NULL DEFAULT FALSE,
    payload_retention_days INT       NOT NULL DEFAULT 7,
    image_retention_days   INT       NOT NULL DEFAULT 7,
    default_model       VARCHAR(128),
    metadata            JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(128) NOT NULL,
    role            VARCHAR(16)  NOT NULL DEFAULT 'client'
                    CHECK (role IN ('admin','client')),
    key_prefix      VARCHAR(16)  NOT NULL UNIQUE,
    key_hash        CHAR(64)     NOT NULL,
    scopes          TEXT[]       NOT NULL DEFAULT ARRAY['chat','completions','embeddings','images','models:read','usage:read'],
    rpm_limit       INT,
    tpm_limit       INT,
    status          VARCHAR(16)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','revoked')),
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    created_by      UUID REFERENCES api_keys(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_has_project CHECK (role = 'admin' OR project_id IS NOT NULL)
);
CREATE INDEX ix_api_keys_project ON api_keys(project_id);

CREATE TABLE providers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(32)  NOT NULL UNIQUE,   -- openai|anthropic|gemini|llamacpp|openvino
    kind            VARCHAR(16)  NOT NULL CHECK (kind IN ('remote','local')),
    display_name    VARCHAR(64)  NOT NULL,
    base_url        TEXT,                           -- lokal: http://127.0.0.1:8100/v1
    api_key_env     VARCHAR(64),                    -- NAMA variabel env (lokal: RUNTIME_TOKEN)
    timeout_seconds INT          NOT NULL DEFAULT 120,
    max_concurrency INT          NOT NULL DEFAULT 16,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE models (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id          UUID NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
    alias                VARCHAR(128) NOT NULL UNIQUE,
    upstream_name        VARCHAR(256) NOT NULL,   -- remote: nama model; lokal: nama model di runtime
    model_type           VARCHAR(16)  NOT NULL
                         CHECK (model_type IN ('chat','completion','embedding','image')),
    tier                 VARCHAR(16)  NOT NULL DEFAULT 'light' CHECK (tier IN ('light','heavy')),
    -- kapabilitas
    supports_streaming   BOOLEAN NOT NULL DEFAULT TRUE,
    supports_tools       BOOLEAN NOT NULL DEFAULT FALSE,
    supports_vision      BOOLEAN NOT NULL DEFAULT FALSE,
    supports_json_mode   BOOLEAN NOT NULL DEFAULT FALSE,
    supports_fim         BOOLEAN NOT NULL DEFAULT FALSE,
    context_window       INT,
    max_output_tokens    INT,
    embedding_dimensions INT,
    -- runtime lokal
    device               VARCHAR(8)  NOT NULL DEFAULT 'remote'
                         CHECK (device IN ('remote','gpu','npu','cpu')),
    runtime_backend      VARCHAR(24)
                         CHECK (runtime_backend IN ('llama_cpp_python','llama_server','openvino_diffusion','openvino_embedding')),
    artifact_path        TEXT,                    -- path .gguf / folder IR OpenVINO (relatif PROJECT_ROOT)
    artifact_sha256      CHAR(64),                -- integritas file model
    vram_mb              INT,                     -- hasil ukur (TASK-09)
    is_pinned            BOOLEAN NOT NULL DEFAULT FALSE,
    license              VARCHAR(64),
    -- biaya
    input_cost_per_mtok  NUMERIC(12,6) NOT NULL DEFAULT 0,
    output_cost_per_mtok NUMERIC(12,6) NOT NULL DEFAULT 0,
    cost_per_image       NUMERIC(12,6) NOT NULL DEFAULT 0,
    is_enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    config               JSONB   NOT NULL DEFAULT '{}'::jsonb,  -- parameter runtime (lihat §9.4)
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_local_has_backend CHECK (device = 'remote' OR runtime_backend IS NOT NULL)
);
CREATE INDEX ix_models_provider ON models(provider_id);
CREATE INDEX ix_models_device   ON models(device) WHERE device <> 'remote';

CREATE TABLE model_routes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias       VARCHAR(128) NOT NULL UNIQUE,
    description TEXT,
    strategy    VARCHAR(16)  NOT NULL DEFAULT 'priority'
                CHECK (strategy IN ('priority','round_robin')),
    is_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_route_targets (
    route_id   UUID NOT NULL REFERENCES model_routes(id) ON DELETE CASCADE,
    model_id   UUID NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    priority   SMALLINT NOT NULL DEFAULT 1,
    weight     SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (route_id, model_id)
);

CREATE TABLE project_allowed_models (
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_pattern VARCHAR(128) NOT NULL,
    PRIMARY KEY (project_id, model_pattern)
);

CREATE TABLE quotas (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    period         VARCHAR(16) NOT NULL CHECK (period IN ('daily','monthly')),
    max_requests   INT,
    max_tokens     BIGINT,
    max_images     INT,
    max_cost_usd   NUMERIC(12,4),
    is_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, period)
);

-- =========================== TRANSAKSI / LOG ===========================
CREATE TABLE requests (
    id                UUID PRIMARY KEY,
    project_id        UUID REFERENCES projects(id) ON DELETE SET NULL,
    api_key_id        UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    endpoint          VARCHAR(64)  NOT NULL
                      CHECK (endpoint IN ('chat.completions','completions','embeddings','images.generations')),
    requested_model   VARCHAR(128) NOT NULL,
    resolved_model_id UUID REFERENCES models(id) ON DELETE SET NULL,
    provider_code     VARCHAR(32),
    upstream_model    VARCHAR(256),
    device            VARCHAR(8),                    -- remote|gpu|npu|cpu (aktual)
    is_stream         BOOLEAN NOT NULL DEFAULT FALSE,
    status            VARCHAR(16) NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','success','error','cancelled')),
    http_status       SMALLINT,
    error_type        VARCHAR(64),
    error_message     TEXT,
    finish_reason     VARCHAR(32),
    prompt_tokens     INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens      INT NOT NULL DEFAULT 0,
    cached_tokens     INT NOT NULL DEFAULT 0,
    image_count       SMALLINT NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(14,8) NOT NULL DEFAULT 0,
    latency_ms        INT,
    ttft_ms           INT,
    load_ms           INT,                           -- waktu load/swap model lokal (jika terjadi)
    queue_ms          INT,                           -- waktu tunggu antrean runtime
    attempts          SMALLINT NOT NULL DEFAULT 0,
    client_ip         INET,
    user_agent        TEXT,
    caller_task       VARCHAR(128),
    caller_agent      VARCHAR(128),
    tags              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);
CREATE INDEX ix_requests_project_time ON requests(project_id, created_at DESC);
CREATE INDEX ix_requests_key_time     ON requests(api_key_id, created_at DESC);
CREATE INDEX ix_requests_status_time  ON requests(status, created_at DESC);
CREATE INDEX ix_requests_caller_task  ON requests(caller_task) WHERE caller_task IS NOT NULL;
CREATE INDEX ix_requests_device_time  ON requests(device, created_at DESC) WHERE device IN ('gpu','npu','cpu');
CREATE INDEX brin_requests_created    ON requests USING BRIN(created_at);

CREATE TABLE request_attempts (
    id            BIGSERIAL PRIMARY KEY,
    request_id    UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    attempt_no    SMALLINT NOT NULL,
    model_id      UUID REFERENCES models(id) ON DELETE SET NULL,
    provider_code VARCHAR(32) NOT NULL,
    device        VARCHAR(8),
    status        VARCHAR(16) NOT NULL CHECK (status IN ('success','error','cancelled')),
    http_status   SMALLINT,
    error_type    VARCHAR(64),
    error_message TEXT,
    latency_ms    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (request_id, attempt_no)
);

CREATE TABLE request_payloads (
    request_id    UUID PRIMARY KEY REFERENCES requests(id) ON DELETE CASCADE,
    request_body  JSONB NOT NULL,
    response_body JSONB,
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_payloads_expires ON request_payloads(expires_at);

CREATE TABLE generated_images (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    model_id        UUID REFERENCES models(id) ON DELETE SET NULL,
    idx             SMALLINT NOT NULL,             -- urutan gambar dalam request
    file_path       TEXT NOT NULL,                 -- relatif terhadap STORAGE_DIR
    mime_type       VARCHAR(32) NOT NULL DEFAULT 'image/png',
    width           SMALLINT NOT NULL,
    height          SMALLINT NOT NULL,
    seed            BIGINT,
    steps           SMALLINT,
    guidance_scale  NUMERIC(4,2),
    sha256          CHAR(64) NOT NULL,
    bytes           INT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (request_id, idx)
);
CREATE INDEX ix_images_project_time ON generated_images(project_id, created_at DESC);
CREATE INDEX ix_images_expires      ON generated_images(expires_at);

CREATE TABLE runtime_events (
    id             BIGSERIAL PRIMARY KEY,
    model_id       UUID REFERENCES models(id) ON DELETE SET NULL,
    model_alias    VARCHAR(128),                  -- snapshot nama untuk histori
    device         VARCHAR(8) NOT NULL CHECK (device IN ('gpu','npu','cpu')),
    event          VARCHAR(24) NOT NULL
                   CHECK (event IN ('load','unload','evict','oom','compile','load_failed',
                                    'device_error','runtime_start','runtime_stop','queue_timeout')),
    reason         TEXT,                          -- mis. 'lru_evict_for:local/qwen2.5-7b'
    duration_ms    INT,
    vram_used_mb   INT,                           -- setelah event
    vram_budget_mb INT,
    request_id     UUID,                          -- request pemicu (jika ada)
    details        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_runtime_events_time  ON runtime_events(created_at DESC);
CREATE INDEX ix_runtime_events_model ON runtime_events(model_id, created_at DESC);

CREATE TABLE usage_daily (
    day               DATE         NOT NULL,
    project_id        UUID         NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_alias       VARCHAR(128) NOT NULL,
    provider_code     VARCHAR(32)  NOT NULL,
    request_count     INT    NOT NULL DEFAULT 0,
    success_count     INT    NOT NULL DEFAULT 0,
    error_count       INT    NOT NULL DEFAULT 0,
    prompt_tokens     BIGINT NOT NULL DEFAULT 0,
    completion_tokens BIGINT NOT NULL DEFAULT 0,
    image_count       INT    NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(16,8) NOT NULL DEFAULT 0,
    PRIMARY KEY (day, project_id, model_alias, provider_code)
);
CREATE INDEX ix_usage_daily_project_day ON usage_daily(project_id, day DESC);

CREATE TABLE audit_logs (
    id            BIGSERIAL PRIMARY KEY,
    actor_key_id  UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    action        VARCHAR(64) NOT NULL,
    entity_type   VARCHAR(32) NOT NULL,
    entity_id     VARCHAR(64),
    before        JSONB,
    after         JSONB,
    ip            INET,
    request_id    UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX ix_audit_time   ON audit_logs(created_at DESC);
```

### 9.3 Aturan data
- **Nilai API key provider tidak pernah disimpan di DB**, hanya nama variabel env.
- API key gateway hanya ditampilkan **sekali** saat dibuat.
- `before/after` di audit log diredaksi.
- Retensi default: `requests` 180 hari; `request_payloads` sesuai project; `generated_images` (baris dan file) sesuai `image_retention_days`; `runtime_events` 90 hari; `usage_daily` permanen.
- Upsert `usage_daily` memakai `INSERT ... ON CONFLICT ... DO UPDATE` (akumulasi).
- **Single source of truth katalog lokal = tabel `models`.** Runtime membaca model ber-`device <> 'remote'` dari DB dan tidak punya file konfigurasi model sendiri.

### 9.4 Isi `models.config` untuk model lokal

```jsonc
// llama_cpp_python (teks/kode)
{"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 512, "flash_attn": true,
 "type_k": "q8_0", "type_v": "q8_0", "chat_format": null,   // null = pakai template GGUF
 "tool_chat_format": "chatml-function-calling", "replicas": 1,
 "auto_reduce_ctx": true, "ctx_fallback": [8192, 4096]}

// FIM (Qwen2.5-Coder-1.5B)
{"n_ctx": 4096, "n_gpu_layers": -1,
 "fim_template": "<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>",
 "fim_stop": ["<|endoftext|>", "<|fim_pad|>", "<|file_sep|>"], "replicas": 1}

// vision (Qwen2-VL-2B)
{"n_ctx": 4096, "n_gpu_layers": -1, "mmproj_path": "local_models/gguf/mmproj-Qwen2-VL-2B-Instruct-f16.gguf",
 "chat_handler": "mtmd", "fallback_backend": "llama_server", "max_image_px": 1280}

// embedding GGUF (nomic)
{"n_ctx": 2048, "n_gpu_layers": -1, "embedding": true, "pooling": "mean",
 "query_prefix": "search_query: ", "document_prefix": "search_document: "}

// openvino_diffusion (SD v1.5)
{"device": "NPU", "component_devices": {"text_encoder": "NPU", "unet": "NPU", "vae_decoder": "NPU"},
 "allowed_sizes": ["512x512"], "default_steps": 25, "max_steps": 50,
 "scheduler": "EulerDiscreteScheduler", "safety_checker": false, "cache_dir": "local_models/ov_cache"}

// openvino_embedding (bge-m3)
{"device": "NPU", "max_seq_len": 512, "static_batch": 8, "pooling": "cls", "normalize": true,
 "cache_dir": "local_models/ov_cache"}
```
Nilai `vram_mb` di kolom terpisah, hasil pengukuran TASK-09.

### 9.5 Seed awal
- Providers: `openai`, `anthropic`, `gemini` (remote); `llamacpp` dan `openvino` (local, `base_url=http://127.0.0.1:8100/v1`, `api_key_env=RUNTIME_TOKEN`).
- Model lokal: seluruh katalog §7.4 dari `scripts/seed_models.yaml`.
- Route default:

| Route | Target (priority) | Keterangan |
|---|---|---|
| `fast` | 1 `local/llama-3.2-3b` · 2 `local/qwen2.5-7b` · 3 model remote murah | task ringan |
| `smart` | 1 Claude (heavy) · 2 GPT (heavy) · 3 `local/qwen2.5-7b` | task berat / agent |
| `local` | 1 `local/qwen2.5-7b` · 2 `local/llama-3.1-8b` | lokal saja (privasi) |
| `code` | 1 `local/qwen2.5-coder-7b` · 2 remote kode · 3 `local/qwen2.5-7b` | chat/agent kode |
| `autocomplete` | 1 `local/qwen2.5-coder-1.5b` | FIM (pinned) |
| `vision` | 1 `local/qwen2-vl-2b` · 2 remote vision | gambar → teks |
| `reason` | 1 `local/deepseek-r1-qwen-7b` · 2 `local/phi-3.5-mini` | reasoning lokal |
| `image` | 1 `local/sd-1.5` | text-to-image |
| `embed-default` | 1 `local/bge-m3` · 2 `local/nomic-embed` · 3 embedding remote | embeddings |

Nama model remote diisi sesuai yang tersedia saat implementasi (cek dokumentasi provider), tidak di-hardcode di kode.

## 10. Spesifikasi API

### 10.1 Konvensi
- Base URL: `http://<host>:8000` (langsung) atau `http://<host>:8080` (via Traefik).
- Auth: `Authorization: Bearer lgw_...` atau `x-api-key`.
- Header caller opsional: `X-Request-ID`, `X-Caller-Task`, `X-Caller-Agent`.
- Header respons: `X-Request-ID`, `X-Gateway-Provider`, `X-Gateway-Model`, `X-Gateway-Device`, `X-Gateway-Attempts`, `X-RateLimit-Remaining-Requests`.
- Format error kompatibel OpenAI:
```json
{"error": {"message": "...", "type": "invalid_request_error", "code": "model_not_found",
           "param": "model", "request_id": "6f1c..."}}
```

| HTTP | `code` | Keterangan |
|---|---|---|
| 400 | `invalid_request` / `capability_not_supported` / `unsupported_size` | |
| 401 | `invalid_api_key` | |
| 403 | `scope_denied` / `model_not_allowed` / `project_suspended` | |
| 404 | `model_not_found` / `image_not_found` | |
| 429 | `rate_limited` / `quota_exceeded` | `Retry-After` |
| 502 | `upstream_error` | Semua kandidat gagal |
| 503 | `model_busy` / `device_unavailable` / `service_unavailable` | Lokal penuh/antrean habis; DB down |
| 504 | `upstream_timeout` | |

### 10.2 Endpoint publik (client key)

| Method | Path | Scope | Keterangan |
|---|---|---|---|
| POST | `/v1/chat/completions` | `chat` | stream & non-stream, tools, vision |
| POST | `/v1/completions` | `completions` | raw prompt + FIM (`suffix`) |
| POST | `/v1/embeddings` | `embeddings` | |
| POST | `/v1/images/generations` | `images` | SD v1.5 |
| GET | `/v1/images/files/{image_id}` | `images` | file PNG (project sama, belum kedaluwarsa) |
| GET | `/v1/models` | `models:read` | model & route yang diizinkan, termasuk `x_device`, `x_capabilities` |
| GET | `/v1/models/{id}` | `models:read` | |
| GET | `/v1/usage` | `usage:read` | usage project sendiri |

Contoh image generation:
```python
img = client.images.generate(
    model="image", prompt="ilustrasi kucing astronaut, gaya cat air",
    size="512x512", n=1, response_format="b64_json",
    extra_body={"negative_prompt": "blurry, low quality", "steps": 25,
                "guidance_scale": 7.5, "seed": 42},
)
```

Contoh vision:
```python
client.chat.completions.create(model="vision", messages=[{"role": "user", "content": [
    {"type": "text", "text": "Apa isi tabel pada gambar ini?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}])
```

### 10.3 Endpoint admin (admin key, prefix `/admin`)

| Method | Path | Keterangan |
|---|---|---|
| GET/POST | `/admin/projects` | |
| GET/PATCH/DELETE | `/admin/projects/{id}` | archive (soft) |
| PUT | `/admin/projects/{id}/allowed-models` | |
| GET/POST | `/admin/projects/{id}/keys` | |
| POST | `/admin/keys/{id}/revoke`, `/admin/keys/{id}/rotate` | |
| GET/PATCH | `/admin/providers`, `/admin/providers/{code}` | |
| POST | `/admin/providers/{code}/test` | |
| GET/POST/PATCH/DELETE | `/admin/models` … | termasuk `is_pinned`, `vram_mb`, `config` |
| GET/POST/PATCH/DELETE | `/admin/routes` … | |
| GET/PUT | `/admin/projects/{id}/quotas` | |
| GET | `/admin/requests`, `/admin/requests/{id}` | filter tambahan: `device` |
| GET | `/admin/usage` | |
| GET | `/admin/audit-logs` | |
| **GET** | **`/admin/runtime/status`** | proksi ke runtime: device, budget, model termuat, antrean |
| **POST** | **`/admin/runtime/models/{alias}/load`** · **`/unload`** | manual (tercatat di audit + runtime_events) |
| **GET** | **`/admin/runtime/events`** | filter model, device, event, waktu |
| POST | `/admin/maintenance/retention` | |
| POST | `/admin/cache/reload` | reload katalog gateway **dan** runtime |

### 10.4 Ops
| Path | Keterangan |
|---|---|
| `GET /health/live` | proses hidup |
| `GET /health/ready` | DB + provider (termasuk runtime: `gpu.ok`, `npu.ok`, model pinned termuat) |
| `GET /metrics` | Prometheus; termasuk `gateway_device_memory_used_mb{device}` |

### 10.5 API internal Local Runtime (127.0.0.1:8100, header `X-Runtime-Token`)
| Method | Path | Keterangan |
|---|---|---|
| POST | `/v1/chat/completions` · `/v1/completions` · `/v1/embeddings` · `/v1/images/generations` | Format OpenAI. `model` = `models.upstream_name`. Respons menyertakan `x_runtime: {device, load_ms, queue_ms}`. |
| GET | `/runtime/status` | device, total/budget/terpakai, model termuat (pinned, in-flight, last_used), antrean |
| POST | `/runtime/models/{name}/load` · `/unload` | |
| POST | `/runtime/catalog/reload` | baca ulang tabel `models` |
| POST | `/runtime/shutdown` | unload semua model dengan rapi, catat `runtime_stop`, lalu keluar (dipakai `stop-all.bat`) |
| GET | `/health/live`, `/health/ready` | ready = device OK + semua model pinned termuat |

Runtime **tidak** melakukan auth project, kuota, atau pencatatan `requests`; semua itu tugas gateway. Runtime hanya mencatat `runtime_events`.

## 11. Keamanan
1. API key: `lgw_` + prefix 8 char + secret 32 byte; hash HMAC-SHA256 dengan pepper; verifikasi constant-time.
2. Scope per key (termasuk `images`); admin endpoint hanya untuk `role=admin`.
3. Secret provider dan `RUNTIME_TOKEN` hanya di `.env`.
4. Redaksi otomatis di logger (`authorization`, `x-api-key`, `x-runtime-token`, `sk-...`, `lgw_...`, `AIza...`).
5. Gateway default bind `127.0.0.1`. **Runtime selalu bind `127.0.0.1`** dan tidak pernah diekspos lewat Traefik.
6. Batas body (default 20 MB). Gambar input vision di-resize ke `max_image_px` sebelum diproses.
7. File model diverifikasi `sha256` saat load pertama. `trust_remote_code=false` untuk konversi/inferensi HF.
8. `GET /v1/images/files/{id}` memeriksa `project_id` pemilik dan path traversal (hanya membaca dari `STORAGE_DIR`).
9. Safety checker SD default off (model base, behavior ditentukan caller), tetapi project dapat meminta `provider_options.safety_checker=true` bila pipeline mendukung. Kebijakan konten adalah tanggung jawab project pemanggil dan dicatat di dokumentasi.

## 12. Logging & Observability

| File | Isi | Rotasi |
|---|---|---|
| `logs/app.log` | log gateway (JSON) | harian, 14 file |
| `logs/error.log` | ≥ ERROR | harian, 30 file |
| `logs/access.log` | 1 baris per HTTP request | harian, 14 file |
| `logs/runtime.log` | log Local Runtime (JSON): load/unload, device, antrean, durasi inferensi | harian, 14 file |
| `logs/runtime-error.log` | ≥ ERROR runtime, termasuk stack dari library native | harian, 30 file |

Field standar gateway: `ts, level, logger, event, request_id, project_slug, key_prefix, model, provider, device, attempt, latency_ms`. Field runtime: `ts, level, event, request_id, model, device, vram_used_mb, queue_ms, load_ms, infer_ms`. `X-Request-ID` diteruskan gateway ke runtime sehingga log kedua proses dapat dikorelasikan.

Konten prompt/response/gambar **tidak** ditulis ke file log.

Implementasi: `structlog` + `TimedRotatingFileHandler` via `QueueHandler`/`QueueListener`, dengan context `contextvars`. Log native llama.cpp (`verbose`) dialihkan ke logger runtime level DEBUG.

## 13. Kebutuhan Non-Fungsional

| ID | Kebutuhan | Target |
|---|---|---|
| NF1 | Overhead gateway (tanpa upstream) | p95 < 30 ms non-stream; TTFT tambahan < 50 ms |
| NF2 | Konkurensi | ≥ 50 stream bersamaan ke remote provider pada 1 worker |
| NF3 | Ketersediaan | Fallback otomatis sebelum token pertama (termasuk `model_busy` lokal) |
| NF4 | Akurasi pencatatan | 100% request berstatus final; sweeper orphan |
| NF5 | Keamanan | 0 secret di log & DB (diuji otomatis) |
| NF6 | Portabilitas | Seluruh start/stop via `.bat`, tanpa admin |
| NF7 | Kualitas kode | type hints, `ruff` bersih, coverage ≥ 70% services & utils |
| NF8 | Async | Tidak ada I/O/inferensi blocking di event loop gateway maupun runtime |
| **NF9** | **Tanpa inferensi CPU** | 100% request lokal tercatat `device ∈ {gpu, npu}` (kecuali dev dengan `ALLOW_CPU_FALLBACK`) |
| **NF10** | **Memori perangkat** | Pemakaian ≤ budget; 0 OOM pada skenario uji swap 100× |
| **NF11** | **Performa lokal (target awal, divalidasi di TASK-20)** | Coder-1.5B FIM TTFT p50 < 300 ms; Qwen2.5-7B ≥ 20 token/s di GPU; swap 7B ≤ 15 detik dari SSD; SD v1.5 512² 25 step di NPU ≤ 30 detik; bge-m3 NPU ≥ 50 kalimat/s |

## 14. Konfigurasi (`.env`)

```dotenv
# ---------- Gateway ----------
APP_ENV=dev
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
LOG_DIR=./logs
TRUST_PROXY=false

DATABASE_URL=postgresql+asyncpg://llm_gateway:CHANGE_ME@127.0.0.1:5432/llm_gateway
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10

GATEWAY_KEY_PEPPER=CHANGE_ME_LONG_RANDOM
DEFAULT_RPM_LIMIT=120
DEFAULT_TPM_LIMIT=200000
MAX_BODY_MB=20
CORS_ORIGINS=
STORAGE_DIR=./storage

OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# ---------- Local Runtime ----------
RUNTIME_HOST=127.0.0.1
RUNTIME_PORT=8100
RUNTIME_URL=http://127.0.0.1:8100/v1
RUNTIME_TOKEN=CHANGE_ME_RANDOM
MODELS_DIR=./local_models
OV_CACHE_DIR=./local_models/ov_cache
HF_HOME=./local_models/hf_cache

LLAMA_GPU_BACKEND=cuda            # cuda (NVIDIA) | vulkan (Intel Arc/AMD)
GPU_TOTAL_MB=8192
GPU_RESERVE_MB=1000
NPU_TOTAL_MB=8192
NPU_RESERVE_MB=700
ALLOW_CPU_FALLBACK=false          # true hanya untuk dev/debug
RUNTIME_QUEUE_TIMEOUT_S=30
RUNTIME_MIN_RESIDENCY_S=60
LOCAL_FIRST_TOKEN_TIMEOUT_S=120
LLAMA_SERVER_EXE=D:\Data.Fahrul\Documents\PortableDev\llama.cpp\llama-server.exe   # backend cadangan
```

## 15. Deployment

### 15.1 Mode A — Tanpa Traefik
```
Client ──► gateway (uvicorn) 127.0.0.1:8000 / 0.0.0.0:8000
           ├─► PostgreSQL portable :5432
           └─► Local Runtime 127.0.0.1:8100 ──► GPU (llama-cpp-python) · NPU (OpenVINO)
```
Urutan `start-all.bat`:
1. `start-postgres.bat` → tunggu port 5432.
2. `migrate.bat`.
3. `start-runtime.bat` → tunggu `/health/ready` runtime. Model pinned (Coder-1.5B, SD v1.5, bge-m3) dimuat dan dikompilasi.
4. `start-gateway.bat` → tunggu `/health/ready` gateway.

### 15.2 Mode B — Dengan Traefik (portable `traefik.exe`)
```
Client ──► Traefik :8080 ──► gateway 127.0.0.1:8000 ──► runtime 127.0.0.1:8100
            dashboard 127.0.0.1:8081
```
- Traefik **hanya** merutekan ke gateway, tidak pernah ke runtime.
- Gateway dijalankan dengan `--behind-proxy`.
- Middleware: `ipAllowList` untuk `/admin`, `rateLimit`, `headers`, access log.
- `respondingTimeouts.writeTimeout: 0s` agar stream panjang dan swap model tidak memutus koneksi.

### 15.3 Autostart (opsional, tanpa admin)
Task Scheduler pada akun user sendiri, trigger *At log on*, action `start-all.bat`.

## 16. Integrasi Klien
- **SDK OpenAI (Python/JS)**: `base_url=http://host:8000/v1`, termasuk `client.images.generate`.
- **LangChain / LlamaIndex / CrewAI / AutoGen**: kelas OpenAI-compatible.
- **Continue / Cline / Aider / Open WebUI**: provider "OpenAI compatible". `autocomplete` dipakai untuk tab-autocomplete (Continue dapat diatur memakai endpoint completions + FIM), sedangkan `code` untuk chat/agent.
- **Cursor**: fitur "Override OpenAI Base URL". Sebagian request Cursor diproses lewat server mereka, sehingga `localhost` bisa tidak terjangkau. Verifikasi perilaku versi terbaru saat implementasi dan siapkan opsi tunnel bila diperlukan.

## 17. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Rate limit in-memory tidak berbagi state antar worker | limit efektif ×N | `APP_WORKERS=1` |
| **Wheel `llama-cpp-python` tidak cocok dengan GPU/driver** | model tidak jalan di GPU | Pilih index wheel sesuai vendor (CUDA/Vulkan). Python 3.10–3.12. Cadangan: `llama-server.exe` prebuilt (CUDA/Vulkan) sebagai `runtime_backend=llama_server`. |
| **Build dari source butuh compiler (VS/MinGW) tanpa admin** | instalasi gagal | Pakai wheel prebuilt. Bila terpaksa build: w64devkit portable + `CMAKE_ARGS`. |
| **Qwen2-VL belum didukung handler di versi llama-cpp-python** | vision gagal | `MTMDChatHandler`. Cadangan: `llama-server.exe --mmproj`. Route `vision` fallback ke remote. |
| **OOM GPU saat swap / KV besar** | crash runtime | Budget + `vram_mb` terukur, KV q8_0, `auto_reduce_ctx`, isolasi proses runtime, supervisor restart di `start-runtime.bat` |
| **Thrashing swap model 7B** | latency tinggi | minimum residency, LRU, routing ke model pinned/remote, metrik `swap_count` |
| **NPU tidak mendukung op tertentu / kompilasi gagal** | SD/embedding gagal | INT8/FP16 alternatif, `component_devices` (mis. VAE ke GPU Intel), cache kompilasi, uji di TASK-09 |
| **Kompilasi NPU lama saat start** | start lambat | `OV_CACHE_DIR` persisten, warmup di background, `ready` menunggu pinned |
| **GPU bukan Intel → device OpenVINO `GPU` tidak ada** | opsi fallback SD terbatas | SD tetap di NPU. Fallback SD via route ke model gambar remote (opsional). |
| Kontensi GPU antara llama.cpp & OpenVINO (bila GPU Intel) | OOM | OpenVINO di GPU hanya bila `vram_mb` dihitung dalam budget GPU yang sama |
| Perbedaan format tool calling | agent error | translator + test kontrak |
| Perubahan API/nama model provider | 404 upstream | nama model di DB |
| PostgreSQL portable mati | request tak tercatat | `/health/ready` gagal → 503 |
| DLL conda tidak ter-load tanpa activate | import error | `scripts/env.bat` |
| Lisensi model | risiko hukum | kolom `license` + `docs/model-catalog.md` |

## 18. Milestone

| Milestone | Task | Hasil |
|---|---|---|
| M1 Fondasi | TASK-01 … TASK-05 | skeleton, config, logger, DB + migrasi, auth |
| M2 Provider Remote | TASK-06 … TASK-08 | abstraksi provider, OpenAI, Claude, Gemini |
| **M3 Local Runtime** | TASK-09 … TASK-12 | hardware probe, unduh & konversi model, runtime + Device Manager, backend llama.cpp & OpenVINO |
| M4 Core API | TASK-13 … TASK-15 | routing/fallback, API v1 (chat, FIM, embeddings, images), usage |
| M5 Governance | TASK-16 … TASK-19 | rate limit, kuota, admin API + runtime admin, health/metrics, retensi |
| M6 Kualitas & Rilis | TASK-20 … TASK-23 | testing + benchmark lokal, deployment tanpa/dengan Traefik, dokumentasi |

## 19. Acceptance Criteria Rilis v1
1. SDK OpenAI resmi dapat memanggil chat (stream & non-stream), tools, embeddings, dan **images** via gateway.
2. **Ke-4 model wajib** (Qwen2.5-7B-Instruct, SD v1.5 OpenVINO, Qwen2.5-Coder-7B dan 1.5B, Qwen2-VL-2B) dan **≥ 4 model llama.cpp tambahan** (Llama-3.2-3B, Llama-3.1-8B, Phi-3.5-mini, DeepSeek-R1-Distill-Qwen-7B, nomic-embed) lulus smoke test.
3. Semua request lokal tercatat `device ∈ {gpu, npu}`; runtime menolak start bila GPU/NPU tidak ada (dengan `ALLOW_CPU_FALLBACK=false`).
4. Uji swap 100× antar model 7–8B tanpa OOM; setiap load/evict tercatat di `runtime_events`.
5. Route `fast`, `smart`, `code`, `autocomplete`, `vision`, `image` berfungsi dengan fallback teruji.
6. Setiap request memiliki baris `requests` final + `request_attempts`; `usage_daily` konsisten (selisih 0), termasuk `image_count`.
7. Key revoked ditolak < 60 detik; kuota & rate limit menghasilkan 429 dengan `Retry-After`.
8. Tidak ada secret di `logs/*.log` maupun DB.
9. `start-all.bat` dan `start-all-traefik.bat` berjalan tanpa admin & tanpa Docker.
10. Target NF11 tercapai atau deviasinya terdokumentasi di `docs/perf-report.md`.

## 20. Glosarium
- **Alias model**: nama publik yang dipakai caller (`local/qwen2.5-7b`).
- **Route**: alias virtual berisi beberapa model kandidat (`fast`, `code`).
- **Attempt**: satu percobaan ke satu provider dalam satu request.
- **Local Runtime**: proses terpisah yang menjalankan model lokal di GPU/NPU.
- **Pinned**: model lokal yang selalu termuat dan tidak pernah di-evict.
- **Swap / eviction**: melepas model dari memori perangkat untuk memuat model lain.
- **FIM (Fill-in-the-Middle)**: completion dengan prefix + suffix untuk autocomplete kode.
- **mmproj**: file proyektor multimodal GGUF untuk model vision.
- **IR OpenVINO**: format model hasil konversi (`.xml` + `.bin`).
- **TTFT**: time to first token.
