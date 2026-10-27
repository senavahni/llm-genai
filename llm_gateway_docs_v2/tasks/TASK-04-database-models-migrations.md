# TASK-04 — Database: PostgreSQL Portable, ORM Models, Alembic

| Item | Nilai |
|---|---|
| Milestone | M1 Fondasi |
| Prioritas | P0 |
| Estimasi | 1.5 hari |
| Dependensi | TASK-02 |
| Referensi PRD | §9 |

## Tujuan
Membuat database `llm_gateway`, koneksi async, model ORM untuk seluruh tabel PRD §9.2, migrasi Alembic, dan seed awal.

## Langkah

### 1. Siapkan database (sekali)
Jalankan `D:\Data.Fahrul\Documents\PortableDev\start-postgres.bat`, lalu dari folder bin PostgreSQL portable:
```bat
psql -h 127.0.0.1 -U postgres -c "CREATE ROLE llm_gateway LOGIN PASSWORD 'GANTI_PASSWORD';"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE llm_gateway OWNER llm_gateway ENCODING 'UTF8';"
psql -h 127.0.0.1 -U postgres -d llm_gateway -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
```
`gen_random_uuid()` sudah built-in sejak PG13; extension `pgcrypto` hanya untuk versi lebih lama. Cek versi dengan `SELECT version();`.

### 2. `scripts/start-postgres.bat` (wrapper)
```bat
@echo off
call "%~dp0env.bat"
call "%PG_START%"
rem tunggu port 5432 siap (maks 30 detik)
"%PY%" scripts\wait_port.py 127.0.0.1 5432 30 || (echo PostgreSQL tidak siap & exit /b 1)
```
`scripts/wait_port.py`: loop `socket.create_connection` hingga sukses/timeout.

### 3. `app/core/database.py`
```python
engine = create_async_engine(settings.database_url, pool_size=..., max_overflow=...,
                             pool_pre_ping=True, pool_recycle=1800)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```
- Untuk penulisan log/usage di background task, gunakan session baru (`async with SessionLocal()`), bukan session dari request.

### 4. ORM (`app/models/`)
- `base.py`: `DeclarativeBase` dengan `MetaData(naming_convention={...})` (ix, uq, ck, fk, pk) agar nama constraint konsisten di migrasi.
- Mixin `TimestampMixin` (`created_at`, `updated_at` dengan `server_default=func.now()`, `onupdate=func.now()`).
- Satu file per agregat: `project.py` (Project, ProjectAllowedModel), `api_key.py`, `provider.py`, `model.py`, `route.py` (ModelRoute, ModelRouteTarget), `quota.py`, `request.py` (Request, RequestAttempt, RequestPayload), `usage.py` (UsageDaily), `audit.py`, **`image.py` (GeneratedImage)**, **`runtime_event.py` (RuntimeEvent)**.
- Kolom baru PRD v2 yang wajib ada:
  - `models`: `device`, `runtime_backend`, `artifact_path`, `artifact_sha256`, `vram_mb`, `is_pinned`, `license`, `supports_fim`, `cost_per_image`, `model_type='image'`, dan CHECK `ck_local_has_backend`.
  - `requests`: `device`, `image_count`, `load_ms`, `queue_ms`, CHECK `endpoint`.
  - `request_attempts.device`.
  - `quotas.max_images`.
  - `usage_daily.image_count`.
  - `projects.image_retention_days`.
  - Scope default `api_keys.scopes` termasuk `images`.
- Package `runtime/` memakai model ORM yang sama (`from app.models import Model, RuntimeEvent`). Jangan menduplikasi definisi tabel.
- Gunakan tipe `UUID(as_uuid=True)`, `JSONB`, `ARRAY(Text)`, `INET`, `Numeric`.
- Semua kolom, CHECK constraint, dan index persis seperti PRD §9.2 (termasuk BRIN & partial index — didefinisikan via `Index(..., postgresql_using="brin")` / `postgresql_where`).

### 5. Alembic
```bat
"%PY%" -m alembic init -t async migrations
```
- `migrations/env.py`: baca `DATABASE_URL` dari settings, `target_metadata = Base.metadata`, `compare_type=True`.
- Revisi awal `0001_initial` dari autogenerate, **dicek manual** (CHECK constraint & BRIN index sering tidak ter-autogenerate → tambahkan manual).
- `scripts/migrate.bat`:
```bat
@echo off
call "%~dp0env.bat"
"%PY%" -m alembic upgrade head
```

### 6. Seed (`scripts/manage.py seed`)
- Insert 5 providers (PRD §9.5): `openai`, `anthropic`, `gemini` (remote), `llamacpp` dan `openvino` (local, `base_url=RUNTIME_URL`, `api_key_env=RUNTIME_TOKEN`). Idempoten (`ON CONFLICT DO NOTHING`).
- Model & route dari `scripts/seed_models.yaml`, berisi **11 model lokal katalog PRD §7.4** (alias, repo, file, device, backend, `artifact_path`, `vram_mb` awal = perkiraan PRD, `is_pinned`, `license`, kapabilitas, `config` §9.4) + contoh model remote + 9 route default (§9.5). Nama model upstream tidak di-hardcode di kode Python.
- `manage.py seed --update-local` memperbarui `vram_mb`, `artifact_sha256`, dan `config` model lokal dari yaml (dipakai setelah pengukuran TASK-09), dan mencatat perubahan di `audit_logs` dengan actor `system`.

Contoh potongan `seed_models.yaml`:
```yaml
models:
  - alias: local/qwen2.5-coder-1.5b
    provider: llamacpp
    upstream_name: qwen2.5-coder-1.5b
    model_type: completion
    tier: light
    device: gpu
    runtime_backend: llama_cpp_python
    hf_repo: Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF     # verifikasi saat TASK-09
    filename: "*q4_k_m*.gguf"
    artifact_path: local_models/gguf/qwen2.5-coder-1.5b-q4_k_m.gguf
    vram_mb: 1300
    is_pinned: true
    supports_fim: true
    license: apache-2.0
    config: {n_ctx: 4096, n_gpu_layers: -1, fim_template: "<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>"}
  - alias: local/sd-1.5
    provider: openvino
    upstream_name: sd15
    model_type: image
    tier: heavy
    device: npu
    runtime_backend: openvino_diffusion
    hf_repo: stable-diffusion-v1-5/stable-diffusion-v1-5
    artifact_path: local_models/openvino/sd15-fp16
    vram_mb: 2500
    is_pinned: true
    license: creativeml-openrail-m
    config: {device: NPU, allowed_sizes: ["512x512"], default_steps: 25, max_steps: 50}
routes:
  - alias: autocomplete
    targets: [{model: local/qwen2.5-coder-1.5b, priority: 1}]
```

## Deliverables
- [ ] Database & role `llm_gateway`
- [ ] `app/core/database.py`, seluruh file `app/models/*`
- [ ] `migrations/` + revisi `0001_initial`
- [ ] `scripts/start-postgres.bat`, `scripts/wait_port.py`, `scripts/migrate.bat`
- [ ] `scripts/manage.py seed` + `scripts/seed_models.yaml`

## Acceptance Criteria
1. `migrate.bat` pada DB kosong membuat seluruh tabel; `\d requests` di psql menampilkan semua index PRD.
2. `alembic downgrade base` lalu `upgrade head` berjalan bersih.
3. `alembic revision --autogenerate` setelah migrasi awal menghasilkan revisi kosong (model & DB sinkron).
4. Seed dapat dijalankan dua kali tanpa duplikasi.
5. Test integrasi: insert Project → ApiKey → Request → RequestAttempt → GeneratedImage, dan cascade delete berfungsi.
6. Seed menghasilkan 11 model lokal + 9 route. Insert model lokal tanpa `runtime_backend` ditolak oleh CHECK constraint.
