# TASK-01 — Setup Environment & Project Skeleton

| Item | Nilai |
|---|---|
| Milestone | M1 Fondasi |
| Prioritas | P0 |
| Estimasi | 0.5 hari |
| Dependensi | — |
| Referensi PRD | §5, §7.3, §14 |

## Tujuan
Menyiapkan repo, struktur folder MVC, dependency Python di env conda `llm-genai`, dan script `.bat` dasar sehingga `uvicorn` bisa menyajikan endpoint kosong.

## Langkah

### 1. Inisialisasi repo (Git portable)
Buka `D:\Data.Fahrul\Documents\PortableDev\Git\git-cmd.exe`:
```bat
cd /d D:\Data.Fahrul\Projects
mkdir llm_gateway && cd llm_gateway
git init
git config core.autocrlf true
```

### 2. Install dependency (Conda Prompt)
Cek versi Python dulu: harus **3.10–3.12**, karena wheel prebuilt `llama-cpp-python` hanya tersedia untuk versi tersebut (PRD §5.1).
```bat
conda activate llm-genai
python --version
pip install fastapi "uvicorn[standard]" pydantic pydantic-settings ^
  "sqlalchemy[asyncio]>=2.0" asyncpg alembic ^
  httpx openai anthropic google-genai ^
  structlog orjson python-dotenv tenacity ^
  prometheus-client
pip install pytest pytest-asyncio respx ruff mypy
pip freeze > requirements.lock.txt
```
Dependency akselerator lokal **dipasang di TASK-09** dan di-pin di `requirements-local.txt`:
- `llama-cpp-python` dari index wheel GPU (CUDA atau Vulkan, sesuai vendor GPU),
- `openvino`, `optimum[openvino]`, `diffusers`, `transformers`, `huggingface_hub`, `pillow`,
- `pynvml` (bila GPU NVIDIA, untuk mengukur VRAM).

Jangan memasang `llama-cpp-python` dari PyPI biasa di tahap ini. Versi default PyPI akan di-build dari source dan hasilnya CPU-only.

Catatan: `uvloop` tidak tersedia di Windows — abaikan jika pip melewatinya.

### 3. Buat struktur folder
Sesuai PRD §7.3, termasuk package **`app/`** (gateway) dan **`runtime/`** (Local Runtime). Setiap package berisi `__init__.py`. Folder `logs/`, `storage/images/`, `local_models/gguf/`, `local_models/openvino/`, `local_models/hf_cache/`, dan `local_models/ov_cache/` berisi `.gitkeep`.

### 4. `scripts/env.bat`
```bat
@echo off
set "CONDA_ENV=D:\Data.Fahrul\.conda\envs\llm-genai"
set "PY=%CONDA_ENV%\python.exe"
set "PATH=%CONDA_ENV%;%CONDA_ENV%\Library\mingw-w64\bin;%CONDA_ENV%\Library\usr\bin;%CONDA_ENV%\Library\bin;%CONDA_ENV%\Scripts;%PATH%"
set "PG_START=D:\Data.Fahrul\Documents\PortableDev\start-postgres.bat"
set "GIT_CMD=D:\Data.Fahrul\Documents\PortableDev\Git\git-cmd.exe"
set "PROJECT_ROOT=%~dp0.."
set "PYTHONUTF8=1"
set "HF_HOME=%PROJECT_ROOT%\local_models\hf_cache"
cd /d "%PROJECT_ROOT%"
rem muat variabel dari .env (baris non-komentar KEY=VALUE)
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
```
Penambahan `Library\bin` ke PATH wajib agar DLL (llama.cpp, OpenVINO, CUDA runtime dari conda, numpy, openssl) termuat tanpa `conda activate`.

### 5. `app/main.py` minimal
```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="LLM Gateway", version="0.1.0")

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    return app

app = create_app()
```

### 6. `scripts/start-gateway.bat` (versi awal)
```bat
@echo off
call "%~dp0env.bat"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. File pendukung
- `.gitignore`: `.env`, `logs/*.log*`, `logs/*.jsonl`, `local_models/**` (kecuali `.gitkeep`), `storage/**`, `__pycache__/`, `.pytest_cache/`, `*.gguf`, `*.bin`.
- `.env.example` sesuai PRD §14.
- `pyproject.toml` berisi konfigurasi `ruff` (line-length 100, target py311) dan `pytest` (`asyncio_mode = "auto"`).
- `requirements.txt` (dependency langsung, versi minimum).

## Deliverables
- [ ] Repo git dengan commit awal
- [ ] Struktur folder lengkap
- [ ] `scripts/env.bat`, `scripts/start-gateway.bat`
- [ ] `.env.example`, `.gitignore`, `pyproject.toml`, `requirements.txt`

## Acceptance Criteria
1. Double-click `start-gateway.bat` → `http://127.0.0.1:8000/health/live` mengembalikan `{"status":"ok"}`.
2. `http://127.0.0.1:8000/docs` menampilkan Swagger UI.
3. `ruff check .` tanpa error.
4. `python -c "import asyncpg, sqlalchemy, httpx"` dari `env.bat` berhasil tanpa conda activate.
5. Versi Python env tercatat di README dan berada di rentang 3.10–3.12.
