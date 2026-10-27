# llm_gateway

Gateway API LLM yang kompatibel dengan OpenAI: remote provider (OpenAI, Anthropic, Gemini) dan
model lokal di GPU/NPU (llama.cpp & OpenVINO lewat proses Local Runtime).
Spesifikasi lengkap: [llm_gateway_docs_v2/docs/PRD.md](llm_gateway_docs_v2/docs/PRD.md),
task: [llm_gateway_docs_v2/tasks/](llm_gateway_docs_v2/tasks/).

Status:
- **M1 Fondasi** (TASK-01 – 05) selesai: skeleton, config, error, logging, DB + migrasi + seed,
  autentikasi API key.
- **M2 Provider Remote** (TASK-06 – 08) selesai: schema unified, registry, util SSE, adapter
  OpenAI, Anthropic, Gemini (diuji dengan mock HTTP; smoke test dengan key asli belum).
- **M3 Local Runtime**: TASK-09 sebagian (probe, script unduh/konversi/ukur, wheel GPU terpasang;
  unduhan & pengukuran penuh belum, lihat [docs/hardware.md](docs/hardware.md)). TASK-10 selesai:
  proses runtime + Device Manager + adapter gateway. Backend nyata llama.cpp/OpenVINO = TASK-11/12.

## Lingkungan

| Komponen | Nilai |
|---|---|
| Python | **3.11.17** (conda env `llm-genai`, `D:\Data.Fahrul\.conda\envs\llm-genai`). Harus 3.10–3.12 agar wheel `llama-cpp-python` tersedia. |
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
  `/v1/embeddings`, `/v1/images/generations`, `GET /runtime/status`,
  `POST /runtime/models/{name}/load?pin=true` · `/unload`, `POST /runtime/catalog/reload`,
  `POST /runtime/shutdown`; tanpa token: `/health/live`, `/health/ready`.
- Provider remote tanpa API key di `.env` otomatis dinonaktifkan (WARNING di log), tidak crash.
- Log JSON: `logs\app.log`, `logs\error.log`, `logs\access.log`, `logs\runtime.log`,
  `logs\runtime-error.log` (rotasi harian, UTC).

## Model lokal (TASK-09)

```bat
call scripts\env.bat
"%PY%" scripts\probe_devices.py                  :: GPU/NPU/RAM → logs\device_probe.json
"%PY%" scripts\download_models.py --dry-run      :: daftar file & ukuran (±27 GB)
"%PY%" scripts\download_models.py --write-yaml   :: unduh + sha256 ke seed_models.yaml
"%PY%" scripts\convert_openvino.py               :: SD v1.5 fp16/int8 + bge-m3 int8
"%PY%" scripts\test_npu.py                       :: uji compile/generate di NPU
"%PY%" scripts\measure_models.py --update-yaml   :: ukur vram_mb, validasi budget
"%PY%" scripts\manage.py seed --update-local     :: sinkron ke DB
```
Akselerator: `requirements-local.txt` (llama-cpp-python wajib dari index wheel GPU).

## CLI (`scripts\manage.py`)

```bat
call scripts\env.bat
"%PY%" scripts\manage.py seed                      :: idempoten: 5 provider, 11 model lokal, 9 route
"%PY%" scripts\manage.py seed --update-local       :: sinkron vram_mb/sha256/config dari yaml (+ audit log)
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
