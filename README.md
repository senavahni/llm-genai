# llm_gateway

Gateway API LLM yang kompatibel dengan OpenAI: remote provider (OpenAI, Anthropic, Gemini) dan
model lokal di GPU/NPU (llama.cpp & OpenVINO lewat proses Local Runtime).
Spesifikasi lengkap: [llm_gateway_docs_v2/docs/PRD.md](llm_gateway_docs_v2/docs/PRD.md),
task: [llm_gateway_docs_v2/tasks/](llm_gateway_docs_v2/tasks/).

Status: **M1 Fondasi** (TASK-01 s.d. TASK-05) selesai: skeleton, config, error, logging, DB +
migrasi + seed, autentikasi API key.

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

- `GET /health/live` → `{"status":"ok"}`; Swagger di `/docs` (hanya bila `APP_ENV=dev` atau `ENABLE_DOCS=true`).
- Log JSON: `logs\app.log`, `logs\error.log`, `logs\access.log` (rotasi harian, UTC).

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
