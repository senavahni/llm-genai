# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/), versi mengikuti
[SemVer](https://semver.org/lang/id/).

## [Unreleased]

### Ditambahkan
- **Embedding lokal v1.0.0 (LGW-V1-01..03)**: `local/qwen3-embedding-0.6b` (Qwen3-Embedding-0.6B,
  OpenVINO INT8, GPU, 1024 dim) lewat backend runtime `openvino_embed`
  (`TextEmbeddingPipeline`), `/v1/embeddings` runtime → provider lokal → route `embed-local`
  (tanpa fallback). Token usage dari tokenizer, biaya 0. `/health/ready` menandai route yang
  seluruh kandidatnya lokal sebagai degraded bila runtime mati. Hasil spike: `docs/hardware.md`.
- Profil `remote-embed-gpu` dan whitelist `RUNTIME_ALLOWED_MODELS` (runtime menolak
  load/compile/warmup model di luar whitelist).
- **Embedding volume besar (LGW-V1-04)**: batch backend dibatasi jumlah input (`max_batch`) dan
  token ber-padding (`max_batch_tokens`), urutan output dijaga; input > `max_input_tokens` →
  `400 input_too_long` + indeks, atau dipotong bila `provider_options.truncate=true`
  (+ `X-Gateway-Warning: input_truncated:N`); `provider_options.input_type=query|document`
  menerapkan `embedding_instructions` model; `dimensions` (MRL 32–1024) hanya untuk model yang
  mendukung; header `X-Priority: interactive|bulk` → antrean prioritas per batch di runtime
  (interactive menyela bulk) + `RUNTIME_BULK_CONCURRENCY`/`RUNTIME_BULK_QUEUE_TIMEOUT_S`.
- **Benchmark embedding GPU (LGW-V1-05)**: `scripts/bench_embed.py` (throughput × batch,
  latensi interactive di bawah bulk, recall vs `embed-default`); hasil di `docs/perf-report.md`.
- **LGW-V1-06**: route `creative` (Claude Sonnet 5.5 → gpt-5) dan `extract` (gpt-5-mini, JSON);
  profil `remote-embed-gpu` memakai `smart` = gpt-5. Header `X-Request-Tags`
  (`job=…,kind=…,stage=…,agent=…`, ≤ 5 pasang, nilai tanpa spasi/`@`; tidak valid → diabaikan +
  warning) disimpan di `requests.tags` (index GIN, migrasi `0006_usage_tags`);
  `GET /admin/usage/by-tag?key=…&match=job:…`. Kuota project memberi
  `X-Gateway-Warning: quota_80pct:<periode>_<metrik>` saat pemakaian ≥ 80% batas.

### Diubah
- Adapter Anthropic: `response_format: json_schema` memakai structured outputs native
  (`output_config.format`), bukan prefill (ditolak model Claude 4.6+); `json_object` tanpa skema
  → instruksi di system prompt.
- **Admin Console** `http://127.0.0.1:8000/console` (HTML/JS/CSS statis tanpa build, CSP
  `script-src 'self'`, `frame-ancestors 'none'`, `no-store`): hanya dari peer loopback + Host lokal.
  Masuk dengan admin key `lgw_` (hanya di memori tab, kunci otomatis 15 menit idle). Menu: Mulai
  (alur key + checklist), Project & Key (buat/rotasi/cabut key, kuota USD, model diizinkan,
  tangguhkan/arsipkan), Provider (status env API key + tes koneksi), File .env. Penjelasan di tiap
  halaman; nilai secret tidak pernah ditampilkan atau diubah dari konsol.
- `GET /admin/env-status`: status variabel `.env` & env API key per provider (nama + keadaan saja).

## [0.1.0] — 2026-10-28

Rilis pertama (M1–M6, TASK-01 s/d TASK-23).

### Ditambahkan
- **Fondasi**: FastAPI + SQLAlchemy async + Alembic, konfigurasi `.env` (pydantic-settings),
  log JSON terstruktur dengan redaksi secret, format error kompatibel OpenAI, API key
  `lgw_<prefix>_<secret>` (HMAC + pepper, hanya tampil sekali).
- **Provider remote**: OpenAI, Anthropic, Gemini lewat skema unified (chat, stream SSE, tools,
  vision, JSON mode, embeddings); provider tanpa key dinonaktifkan otomatis.
- **Local Runtime** (proses terpisah, `127.0.0.1:8100`, token wajib): Device Manager per device
  (budget memori, model pinned, LRU + min residency, antrean → `model_busy`, tolak CPU), backend
  OpenVINO GenAI untuk Qwen2.5-7B, Qwen2.5-Coder-7B, Qwen2.5-Coder-1.5B (FIM di NPU, TTFT
  ±250 ms), Qwen2-VL-2B (vision), Stable Diffusion v1.5 (text→image & image→image di NPU);
  tool calling Hermes, JSON mode lewat grammar, cancel stream, supervisor restart.
- **Router**: route virtual (`smart`, `fast`, `local`, `code`, `autocomplete`, `vision`, `image`,
  `embed-default`), priority / round robin / `prefer_loaded`, fallback sebelum token pertama,
  circuit breaker, filter kapabilitas & pola model per project.
- **API publik v1**: `/v1/chat/completions`, `/v1/completions` (raw & FIM), `/v1/embeddings`,
  `/v1/images/generations`, `/v1/images/edits`, `/v1/images/files/*`, `/v1/models`, `/v1/usage`;
  header `X-Gateway-Model/Provider/Device`, `X-Request-ID`, `X-RateLimit-*`.
- **Pencatatan**: setiap request (`requests`, `request_attempts`, payload opsional), agregat
  `usage_daily`, biaya Decimal, fallback JSONL saat DB mati + replay, orphan sweeper.
- **Rate limit & kuota**: RPM sliding window + TPM token bucket per key, kuota harian/bulanan per
  project (request, token, gambar, biaya) dengan `Retry-After`.
- **Admin API** + audit log atomik: project, key (buat/revoke/rotasi), kuota, provider, model,
  route, laporan request/usage/audit, status & load/unload runtime, reload cache.
- **Observability**: `/health/live`, `/health/ready` (ready/degraded/not_ready, detail runtime
  termasuk RAM sistem), `/metrics` Prometheus gabungan gateway + runtime.
- **Maintenance**: retensi harian 00:30 UTC (payload, gambar, requests 180 hari, audit 730 hari,
  runtime events 90 hari), backup `pg_dump` + verifikasi restore, CLI `retention`,
  `export-usage`, `verify-models`, `clear-ov-cache`.
- **Kualitas**: unit, integrasi (PostgreSQL nyata), contract (SDK `openai` ke uvicorn), load test,
  test hardware lewat gateway, benchmark lokal, secret scan; `scripts\check.bat`.
- **Deployment** tanpa admin/Docker: `start-all.bat` / `stop-all.bat` (Mode A, opsi `--lan`,
  `--no-runtime`), Traefik portable (Mode B: allowlist IP `/admin`, rate limit global, header
  keamanan, TLS opsional).
- **Dokumentasi**: integrasi klien (SDK, framework, coding assistant), katalog model, database,
  operasional, deployment, laporan performa.

- **Provider API pihak ketiga tak terbatas**: `POST/PATCH/DELETE /admin/providers` dengan adapter
  `openai` / `anthropic` / `gemini` (DeepSeek, Groq, OpenRouter, Mistral, Ollama/vLLM, ...),
  provider tanpa key (`config.auth: none`), header statis non-secret; `api_key_env` remote wajib
  berpola `*_API_KEY` sehingga secret internal gateway tidak bisa dikirim ke API pihak ketiga.
- **Profil operasional** (`scripts/profiles/`: `remote-only`, `ram16`, `full`) +
  `manage.py apply-profile` (ter-audit): mengatur model/provider aktif & isi route tanpa
  mengubah katalog atau klien.
- Qwen2.5-Coder-1.5B melayani chat + FIM + tools dari satu salinan; Qwen2-VL-2B mendukung tools
  (render Hermes manual).

### Keputusan desain
- Inferensi lokal hanya OpenVINO di GPU/NPU (llama.cpp dihapus); tidak ada embedding lokal.
- Gateway selalu 1 worker (rate limiter, kuota berjalan, circuit breaker in-memory).
- Rilis ini berjalan dengan profil `remote-only` (semua model lokal nonaktif sementara karena RAM
  16 GB tidak cukup untuk model 7B + aplikasi lain).

### Diketahui
- Lihat bagian "Deviasi" di [docs/perf-report.md](docs/perf-report.md): throughput 1 worker,
  token/s model 7B di iGPU, dan kebutuhan RAM bebas untuk swap model GPU.
