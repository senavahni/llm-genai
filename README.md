# llm_gateway

Gateway API LLM yang kompatibel dengan OpenAI: remote provider (OpenAI, Anthropic, Gemini) dan
model lokal Qwen + Stable Diffusion v1.5 di GPU/NPU Intel (OpenVINO lewat proses Local Runtime,
tanpa inferensi CPU).
Spesifikasi lengkap: [llm_gateway_docs_v2/docs/PRD.md](llm_gateway_docs_v2/docs/PRD.md),
task: [llm_gateway_docs_v2/tasks/](llm_gateway_docs_v2/tasks/).

Status:
- **M1 Fondasi** (TASK-01 – 05) selesai: skeleton, config, error, logging, DB + migrasi + seed,
  autentikasi API key.
- **M2 Provider Remote** (TASK-06 – 08) selesai: schema unified, registry, util SSE, adapter
  OpenAI, Anthropic, Gemini (diuji dengan mock HTTP; smoke test dengan key asli belum).
- **M3 Local Runtime**: TASK-09 (probe, unduh/konversi OpenVINO IR, ukur, smoke test; lihat
  [docs/hardware.md](docs/hardware.md)). TASK-10 selesai: proses runtime + Device Manager +
  adapter gateway. Backend nyata OpenVINO GenAI = TASK-11 (Qwen) / TASK-12 (SD).

## Lingkungan

| Komponen | Nilai |
|---|---|
| Python | **3.11.17** (conda env `llm-genai`, `D:\Data.Fahrul\.conda\envs\llm-genai`). Perintah lewat `scripts\conda-run.bat` (aktivasi Miniconda + env). |
| PostgreSQL | portable 18.x, `D:\Data.Fahrul\Documents\PortableDev\start-postgres.bat` |
| OS | Windows tanpa admin, tanpa Docker |

## Setup pertama kali

1. Dependency (Conda Prompt): `conda activate llm-genai` lalu `pip install -r requirements.txt`
   (versi persis di `requirements.lock.txt`).
2. Salin `.env.example` → `.env` dan ganti semua `CHANGE_ME`. `GATEWAY_KEY_PEPPER` dan
   `RUNTIME_TOKEN` minimal 32 karakter:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Jangan menaruh komentar di akhir baris nilai, karena `scripts\env.bat` membaca `.env` per baris.
3. Database (sekali saja, sebagai superuser `postgres`):
   ```bat
   psql -h 127.0.0.1 -U postgres -c "CREATE ROLE llm_gateway LOGIN PASSWORD '...';"
   psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE llm_gateway OWNER llm_gateway ENCODING 'UTF8';"
   psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE llm_gateway_test OWNER llm_gateway ENCODING 'UTF8';"
   ```
4. `scripts\start-postgres.bat` → `scripts\migrate.bat` → `"%PY%" scripts\manage.py seed`
5. Admin key bootstrap: `"%PY%" scripts\manage.py create-admin-key --name bootstrap`
   (key hanya ditampilkan sekali).

## Menjalankan

| Script | Fungsi |
|---|---|
| `scripts\env.bat` | PATH DLL conda + variabel `.env`, tanpa `conda activate` |
| `scripts\start-postgres.bat` | start PostgreSQL portable, tunggu port 5432 |
| `scripts\migrate.bat` | `alembic upgrade head` |
| `scripts\start-gateway.bat` | uvicorn `127.0.0.1:8000` (dev, `--reload`) |
| `scripts\start-runtime.bat` | Local Runtime `127.0.0.1:8100` dengan supervisor (restart bila crash, maks 5x beruntun; log `logs\runtime-supervisor.log`) |

- Gateway: `GET /health/live`, `GET /health/ready` (`ok` / `degraded` bila ada provider mati,
  503 bila DB mati). Swagger di `/docs` (hanya bila `APP_ENV=dev` atau `ENABLE_DOCS=true`).
- Runtime (header `X-Runtime-Token` = `RUNTIME_TOKEN`): `/v1/chat/completions`, `/v1/completions`,
  `/v1/images/generations`, `/v1/images/edits` (image-to-image, body JSON + `image` base64),
  `GET /runtime/status`,
  `POST /runtime/models/{name}/load?pin=true` · `/unload`, `POST /runtime/catalog/reload`,
  `POST /runtime/shutdown`; tanpa token: `/health/live`, `/health/ready`.
- Provider remote tanpa API key di `.env` otomatis dinonaktifkan (WARNING di log), tidak crash.
- Log JSON: `logs\app.log`, `logs\error.log`, `logs\access.log`, `logs\runtime.log`,
  `logs\runtime-error.log` (rotasi harian, UTC).

## Model lokal (TASK-09)

```bat
scripts\conda-run.bat python scripts\probe_devices.py                 :: GPU/NPU/RAM → logs\device_probe.json
scripts\conda-run.bat python scripts\download_models.py --write-yaml  :: IR siap pakai (Qwen2.5 7B) + sha256
scripts\conda-run.bat python scripts\convert_openvino.py --write-yaml :: SD v1.5, Qwen2-VL-2B, Coder-1.5B (NPU)
scripts\conda-run.bat python scripts\test_sd.py                       :: SD t2i + i2i di NPU
scripts\conda-run.bat python scripts\measure_models.py --update-yaml  :: ukur vram_mb, cpu_ratio, budget
scripts\conda-run.bat python scripts\smoke_local.py                   :: uji kualitas → docs\smoke\
scripts\conda-run.bat python scripts\manage.py seed --update-local    :: sinkron ke DB
```
Akselerator: `requirements-local.txt` (openvino + openvino-genai, satu versi).

## CLI (`scripts\manage.py`)

```bat
call scripts\env.bat
"%PY%" scripts\manage.py seed                      :: idempoten: 4 provider, 5 model lokal, 8 route
"%PY%" scripts\manage.py seed --update-local       :: samakan model lokal dengan yaml, nonaktifkan yang dihapus (+ audit log)
"%PY%" scripts\manage.py create-project --slug agent-a --name "Agent A"
"%PY%" scripts\manage.py create-key --project agent-a --name dev --scopes chat,models:read
```

## Test & kualitas

```bat
call scripts\env.bat
"%PY%" -m pytest           :: test integrasi memakai DB llm_gateway_test (dimigrasi ulang otomatis)
"%PY%" -m ruff check .
"%PY%" -m mypy app
```
