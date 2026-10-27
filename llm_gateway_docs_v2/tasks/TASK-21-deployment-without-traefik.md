# TASK-21 — Deployment Mode A: Tanpa Traefik

| Item | Nilai |
|---|---|
| Milestone | M6 Kualitas & Rilis |
| Prioritas | P0 |
| Estimasi | 1 hari |
| Dependensi | TASK-04, TASK-10, TASK-18 |
| Referensi PRD | §15.1, §15.3 |

## Tujuan
Menjalankan seluruh stack (PostgreSQL portable → migrasi → **Local Runtime** (GPU + NPU) → gateway) dengan satu klik, tanpa admin & tanpa Docker.

## Topologi
```
Client ──► gateway 127.0.0.1:8000  (atau 0.0.0.0:8000 untuk akses LAN)
           ├── PostgreSQL portable 127.0.0.1:5432
           └── Local Runtime 127.0.0.1:8100 (SELALU localhost)
                ├── GPU: llama-cpp-python (+ llama-server cadangan, port 8110–8199)
                └── NPU: OpenVINO (SD v1.5, bge-m3)
```

## Script

### `scripts/run_server.py`
```python
import argparse, uvicorn
from app.core.config import get_settings

p = argparse.ArgumentParser()
p.add_argument("--lan", action="store_true")
p.add_argument("--behind-proxy", action="store_true")
a = p.parse_args()
s = get_settings()
uvicorn.run(
    "app.main:app",
    host="0.0.0.0" if a.lan else s.app_host,
    port=s.app_port,
    workers=1,                      # wajib: rate limiter in-memory
    timeout_keep_alive=75,
    access_log=False,               # diganti access log sendiri (TASK-03)
    log_config=None,                # logging diatur setup_logging()
    proxy_headers=a.behind_proxy,
    forwarded_allow_ips="127.0.0.1" if a.behind_proxy else None,
)
```

### `scripts/start-gateway.bat` (versi produksi)
```bat
@echo off
call "%~dp0env.bat"
if "%APP_ENV%"=="" set "APP_ENV=prod"
"%PY%" scripts\run_server.py %*
```

### `scripts/start-all.bat`
```bat
@echo off
setlocal
call "%~dp0env.bat"
echo [1/5] PostgreSQL...
start "postgres" /min cmd /c ""%~dp0start-postgres.bat""
"%PY%" scripts\wait_port.py 127.0.0.1 5432 60 || goto :fail

echo [2/5] Migrasi database...
call "%~dp0migrate.bat" || goto :fail

echo [3/5] Verifikasi file model...
"%PY%" scripts\manage.py verify-models --quick || echo PERINGATAN: ada model hilang, lihat logs\app.log

echo [4/5] Local Runtime (GPU/NPU) - warmup model pinned...
start "llm-runtime" /min cmd /c ""%~dp0start-runtime.bat""
rem timeout panjang: compile NPU pertama kali (tanpa cache) bisa beberapa menit
"%PY%" scripts\healthcheck.py http://127.0.0.1:8100/health/ready 900 --token-env RUNTIME_TOKEN || goto :fail

echo [5/5] Gateway...
start "llm-gateway" cmd /k ""%~dp0start-gateway.bat" %*"
"%PY%" scripts\healthcheck.py http://127.0.0.1:8000/health/ready 60 || goto :fail
echo Gateway siap di http://127.0.0.1:8000
exit /b 0
:fail
echo GAGAL - cek folder logs\
exit /b 1
```
- `start-runtime.bat` (TASK-10) sudah berisi supervisor restart.
- Variabel `.env` dimuat oleh `env.bat` (TASK-01).
- Opsi `start-all.bat --no-runtime`: lewati langkah 4 (hanya provider remote). Gateway tetap jalan dengan status `degraded`.

### `scripts/stop-all.bat`
- Urutan: gateway → runtime → PostgreSQL.
- Gateway: `taskkill /FI "WINDOWTITLE eq llm-gateway*" /T /F`.
- Runtime: kirim dulu `POST /runtime/shutdown` (token) agar model di-unload rapi dan event `runtime_stop` tercatat. Tunggu 15 detik, lalu `taskkill /FI "WINDOWTITLE eq llm-runtime*" /T /F` sebagai cadangan. `/T` ikut mematikan subprocess `llama-server.exe` cadangan.
- Semua tanpa admin karena proses milik user sendiri.
- Hentikan PostgreSQL dengan `pg_ctl stop -D <data_dir> -m fast` (gunakan script stop bawaan PortableDev bila ada) — **jangan** `taskkill /F` pada postgres agar data aman.

### Akses LAN (opsional)
- `start-all.bat --lan` → bind `0.0.0.0`. Windows Firewall mungkin menampilkan prompt; jika tidak bisa diizinkan tanpa admin, gunakan mode localhost saja atau Traefik di port yang diizinkan.
- Sangat disarankan mode Traefik (TASK-22) bila diakses dari mesin lain, agar `/admin` dibatasi IP.

### Autostart (tanpa admin)
- Task Scheduler → Create Task (akun sendiri) → Trigger *At log on* → Action `scripts\start-all.bat` → "Run only when user is logged on".

## Deliverables
- [ ] `start-gateway.bat` + `run_server.py`, `start-all.bat` (dengan opsi `--lan`, `--no-runtime`), `stop-all.bat`
- [ ] Endpoint `POST /runtime/shutdown`
- [ ] Pembacaan `.env` di `env.bat`
- [ ] `docs/deployment.md` bagian Mode A

## Acceptance Criteria
1. Dari kondisi semua mati, dengan cache OpenVINO sudah ada, `start-all.bat` menyalakan stack dan `/health/ready` gateway siap < 3 menit, dengan model pinned (Coder-1.5B, SD v1.5, bge-m3) termuat. Start pertama tanpa cache didokumentasikan durasinya.
1b. Runtime di-kill paksa → supervisor menyalakannya kembali; gateway tetap hidup.
2. `stop-all.bat` mematikan semua proses (termasuk `llama-server.exe` cadangan); VRAM GPU kembali bebas; PostgreSQL berhenti bersih.
3. Semua dilakukan tanpa hak admin dan tanpa Docker.
4. Log tiap komponen ada di `logs\`.
