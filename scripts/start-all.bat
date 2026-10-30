@echo off
rem Nyalakan seluruh stack Mode A (tanpa Traefik), tanpa admin & tanpa Docker:
rem   PostgreSQL portable -> migrasi -> verifikasi model -> Local Runtime (GPU/NPU) -> gateway
rem Opsi:
rem   --lan          gateway bind 0.0.0.0 (akses dari mesin lain; lihat docs\deployment.md)
rem   --no-runtime   lewati Local Runtime (hanya provider remote; /health/ready = degraded)
rem   --behind-proxy dipakai start-all-traefik.bat (Mode B)
setlocal
rem simpan folder script SEBELUM shift: shift ikut menggeser %0 sehingga %~dp0 berubah
set "HERE=%~dp0"
call "%HERE%env.bat"

set "GW_ARGS="
set "NO_RUNTIME="
:args
if "%~1"=="" goto :argsdone
if /i "%~1"=="--no-runtime" (set "NO_RUNTIME=1") else (set "GW_ARGS=%GW_ARGS% %~1")
shift
goto :args
:argsdone
if "%APP_PORT%"=="" set "APP_PORT=8000"
if "%RUNTIME_PORT%"=="" set "RUNTIME_PORT=8100"

echo [1/5] PostgreSQL...
"%PY%" scripts\wait_port.py 127.0.0.1 5432 1 >nul 2>&1 && (echo       sudah berjalan) || (
  call "%HERE%start-postgres.bat" || goto :fail
)

echo [2/5] Migrasi database...
call "%HERE%migrate.bat" || goto :fail

echo [3/5] Verifikasi file model...
"%PY%" scripts\manage.py verify-models --quick || echo PERINGATAN: ada model hilang, jalankan "scripts\conda-run.bat python scripts\manage.py verify-models"

if defined NO_RUNTIME (
  echo [4/5] Local Runtime dilewati ^(--no-runtime^)
  goto :gateway
)
echo [4/5] Local Runtime (GPU/NPU) - warmup model pinned...
"%PY%" scripts\wait_port.py 127.0.0.1 %RUNTIME_PORT% 1 >nul 2>&1 && (echo       sudah berjalan) || (
  start "llm-runtime" /min cmd /c ""%HERE%start-runtime.bat""
)
rem timeout panjang: compile NPU pertama kali (tanpa cache) bisa beberapa menit
"%PY%" scripts\healthcheck.py http://127.0.0.1:%RUNTIME_PORT%/health/ready 900 --token-env RUNTIME_TOKEN || goto :fail

:gateway
echo [5/5] Gateway...
"%PY%" scripts\wait_port.py 127.0.0.1 %APP_PORT% 1 >nul 2>&1 && (echo       sudah berjalan) || (
  start "llm-gateway" /min cmd /c ""%HERE%start-gateway.bat"%GW_ARGS%"
)
"%PY%" scripts\healthcheck.py http://127.0.0.1:%APP_PORT%/health/ready 60 || goto :fail
echo Gateway siap di http://127.0.0.1:%APP_PORT%   (log: logs\app.log, logs\runtime.log)
exit /b 0

:fail
echo GAGAL - cek folder logs\ (app.log, runtime.log, runtime-supervisor.log)
exit /b 1
