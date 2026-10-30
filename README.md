# llm_gateway

Gateway API LLM **kompatibel OpenAI** untuk banyak project/agent di satu mesin Windows:

- **Provider remote**: OpenAI, Anthropic, Gemini, plus **API pihak ketiga berapa pun**
  (DeepSeek, Groq, OpenRouter, Mistral, Ollama/vLLM di LAN, ...) yang ditambahkan lewat Admin API
  dengan adapter OpenAI/Anthropic/Gemini-compatible tanpa ubah kode (key di `.env`).
- **Model lokal** di iGPU + NPU Intel lewat **OpenVINO** (proses Local Runtime terpisah), tanpa
  inferensi CPU: Qwen2.5-7B, Qwen2.5-Coder-7B, Qwen2.5-Coder-1.5B (FIM), Qwen2-VL-2B (vision),
  Stable Diffusion v1.5 (text→image, image→image).
- **Route** (`smart`, `fast`, `code`, `autocomplete`, `vision`, `image`, ...) dengan fallback
  otomatis, circuit breaker, dan antrean/swap model lokal per device.
- **API key per project**, pola model yang diizinkan, rate limit RPM/TPM, kuota harian/bulanan,
  pencatatan token & biaya per request ke PostgreSQL, Admin API + audit log, metrics Prometheus.

Tanpa hak admin, tanpa Docker: conda env + PostgreSQL portable (+ Traefik portable opsional).

> **Status (30 Okt 2026): profil `remote-only`.** Semua model lokal dinonaktifkan sementara agar
> mesin ringan (file & cache tetap ada); jalankan dengan `scripts\start-all.bat --no-runtime`.
> Aktifkan kembali dengan `manage.py apply-profile ram16` / `full` (lihat
> [docs/model-catalog.md](docs/model-catalog.md#profil-operasional)).
Spesifikasi: [PRD](llm_gateway_docs_v2/docs/PRD.md) · task: [llm_gateway_docs_v2/tasks/](llm_gateway_docs_v2/tasks/).

```
Client ──► [Traefik :8080, opsional] ──► gateway :8000 ──┬─► OpenAI / Anthropic / Gemini
                                                        ├─► PostgreSQL :5432
                                                        └─► Local Runtime 127.0.0.1:8100
                                                             ├─ iGPU: Qwen 7B / VL (swap)
                                                             └─ NPU: Coder-1.5B, SD v1.5 (pinned)
```

## Dokumentasi

| Dokumen | Isi |
|---|---|
| [docs/client-integration.md](docs/client-integration.md) | **memakai gateway dari project lain**: SDK Python/JS, curl, LangChain, LlamaIndex, Continue, Cline, Aider, Open WebUI, Cursor, error & retry |
| [docs/model-catalog.md](docs/model-catalog.md) | model lokal & remote, lisensi, route, memilih model, menambah model |
| [docs/deployment.md](docs/deployment.md) | Mode A (tanpa Traefik) & Mode B (Traefik), start/stop, autostart |
| [docs/operations.md](docs/operations.md) | log, backup/restore, retensi, rotasi key, troubleshooting |
| [docs/admin-api.http](docs/admin-api.http) | koleksi request Admin API (project, key, kuota, model, route, laporan) |
| [docs/database.md](docs/database.md) | ERD, arti tabel, query siap pakai |
| [docs/hardware.md](docs/hardware.md) | probe device, keputusan backend, pengukuran memori |
| [docs/perf-report.md](docs/perf-report.md) | load test, benchmark lokal (NF1–NF11), deviasi |
| [CHANGELOG.md](CHANGELOG.md) | riwayat versi |

## Prasyarat

| Komponen | Nilai |
|---|---|
| OS | Windows 10/11 64-bit, akun biasa (tanpa admin) |
| Hardware | Intel Core Ultra (iGPU Intel Arc/Graphics + NPU Intel AI Boost) dengan driver GPU & NPU terbaru; **RAM ≥ 16 GB** (GPU/NPU memakai RAM sistem, lihat [perf-report](docs/perf-report.md#ram-sistem)); disk kosong **≥ 40 GB** (model ±12 GB + cache compile ±12 GB) |
| Python | conda env Python 3.11 (`D:\Data.Fahrul\.conda\envs\llm-genai`; ubah `CONDA_ENV` di `scripts\env.bat`) |
| PostgreSQL | portable ≥ 14 (terpasang 18.x di `PortableDev\postgres`) |
| Git | Git portable (`PortableDev\Git`, juga menyediakan `openssl.exe` untuk TLS) |
| Traefik | opsional, v3 portable (`PortableDev\traefik\traefik.exe`), Mode B |

## Quick start (dari nol)

```bat
:: 1. clone (Git portable: git-cmd.exe)
git clone <repo> llm-genai && cd llm-genai

:: 2. dependency (Conda Prompt)
conda activate llm-genai
pip install -r requirements.txt -r requirements-local.txt
:: torch CPU hanya untuk konversi model (bukan inferensi):
pip install torch --index-url https://download.pytorch.org/whl/cpu

:: 3. konfigurasi: salin lalu isi semua CHANGE_ME (pepper & runtime token >= 32 karakter acak:
::    python -c "import secrets; print(secrets.token_urlsafe(48))")
copy .env.example .env

:: 4. database (sekali, sebagai superuser postgres)
psql -h 127.0.0.1 -U postgres -c "CREATE ROLE llm_gateway LOGIN PASSWORD '...';"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE llm_gateway OWNER llm_gateway ENCODING 'UTF8';"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE llm_gateway_test OWNER llm_gateway ENCODING 'UTF8';"
scripts\start-postgres.bat
scripts\migrate.bat
scripts\conda-run.bat python scripts\manage.py seed

:: 5. model lokal (±1 jam; lihat docs\model-catalog.md & docs\hardware.md)
scripts\conda-run.bat python scripts\probe_devices.py
scripts\conda-run.bat python scripts\download_models.py --write-yaml
scripts\conda-run.bat python scripts\convert_openvino.py --write-yaml
scripts\conda-run.bat python scripts\smoke_local.py         :: uji + hangatkan cache compile
scripts\conda-run.bat python scripts\test_sd.py
scripts\conda-run.bat python scripts\measure_models.py --update-yaml
scripts\conda-run.bat python scripts\manage.py seed --update-local

:: 6. admin key (tampil sekali) lalu jalankan semuanya
scripts\conda-run.bat python scripts\manage.py create-admin-key --name ops
scripts\start-all.bat
```

Buat project + key untuk klien lewat Admin API ([docs/admin-api.http](docs/admin-api.http)) atau CLI:
```bat
scripts\conda-run.bat python scripts\manage.py create-project --slug agent-a --name "Agent A" --allow "smart,fast,code,autocomplete,vision,image"
scripts\conda-run.bat python scripts\manage.py create-key --project agent-a --name dev
```
Lalu ikuti [docs/client-integration.md](docs/client-integration.md).

## Script

| Script | Fungsi |
|---|---|
| `scripts\start-all.bat [--lan] [--no-runtime]` | PostgreSQL → migrasi → verifikasi model → runtime → gateway (Mode A) |
| `scripts\start-all-traefik.bat` | sama, gateway `--behind-proxy` + Traefik :8080 (Mode B) |
| `scripts\stop-all.bat [--keep-db]` | Traefik → gateway → runtime (unload rapi) → PostgreSQL |
| `scripts\start-gateway.bat [--lan\|--behind-proxy\|--reload]` | gateway saja (`run_server.py`, 1 worker) |
| `scripts\start-runtime.bat` | Local Runtime + supervisor restart |
| `scripts\start-traefik.bat` | Traefik portable |
| `scripts\start-postgres.bat`, `scripts\migrate.bat` | PostgreSQL portable, `alembic upgrade head` |
| `scripts\backup-db.bat [--verify]` | `pg_dump` ke `backups\` (7 terakhir) |
| `scripts\check.bat` | ruff, format, mypy, pytest + coverage ≥ 70%, secret scan |
| `scripts\test.bat [args]` | pytest (unit + integrasi + contract; `--load`, `--live` opsional) |
| `scripts\test-hardware.bat [file]` | test model nyata di GPU/NPU (manual, mesin target) |
| `scripts\bench.bat` | benchmark model lokal → `docs\perf-report.md` |
| `scripts\conda-run.bat <cmd>` | jalankan perintah di conda env (dengan `.env`) |
| `scripts\env.bat` | dipanggil semua script: PATH DLL conda + variabel `.env` |

CLI `scripts\manage.py`: `seed [--update-local]`, `apply-profile <remote-only|ram16|full>`,
`create-admin-key`, `create-project`,
`allow-models`, `create-key`, `replay-usage`, `retention`, `export-usage`, `verify-models`,
`clear-ov-cache` (`--help` per perintah).

## Endpoint

| Path | Akses |
|---|---|
| `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/images/generations`, `/v1/images/edits`, `/v1/images/files/...`, `/v1/models`, `/v1/usage` | key client |
| `/admin/*` (project, key, kuota, provider, model, route, requests, usage, audit, runtime, maintenance) | key admin |
| `/health/live`, `/health/ready` | publik (detail hanya dari localhost / key admin) |
| `/metrics` | localhost atau key admin |
| `/docs` | hanya `APP_ENV=dev` atau `ENABLE_DOCS=true` |

## Pengembangan

```bat
scripts\check.bat                         :: gerbang kualitas lengkap (PostgreSQL harus hidup)
scripts\test.bat tests\unit -q
scripts\start-gateway.bat --reload        :: dev
```
Test integrasi memakai DB `llm_gateway_test` (dimigrasi ulang otomatis tiap sesi).
