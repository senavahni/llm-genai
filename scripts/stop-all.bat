@echo off
rem Matikan stack: Traefik (bila ada) -> gateway -> runtime (unload rapi) -> PostgreSQL
rem (pg_ctl -m fast). Tanpa admin. Opsi: --keep-db  biarkan PostgreSQL tetap hidup
setlocal
call "%~dp0env.bat"

"%PY%" scripts\wait_port.py 127.0.0.1 8080 1 >nul 2>&1 && (
  echo [0/3] Traefik...
  taskkill /FI "WINDOWTITLE eq traefik*" /T /F >nul 2>&1
)

if "%APP_PORT%"=="" set "APP_PORT=8000"
echo [1/3] Gateway...
rem taskkill /FI selalu exit 0 walau tidak ada yang cocok -> status dari port
"%PY%" scripts\wait_port.py 127.0.0.1 %APP_PORT% 1 >nul 2>&1 || echo       tidak berjalan
taskkill /FI "WINDOWTITLE eq llm-gateway*" /T /F >nul 2>&1
"%PY%" scripts\wait_port.py 127.0.0.1 %APP_PORT% 1 >nul 2>&1 && echo       PERINGATAN: port %APP_PORT% masih dipakai proses lain
rem request yang sedang berjalan saat dimatikan tercatat 'pending' lalu disapu orphan sweeper

echo [2/3] Local Runtime...
"%PY%" scripts\runtime_ctl.py shutdown --wait 15 || (
  echo       shutdown rapi gagal, taskkill...
  taskkill /FI "WINDOWTITLE eq llm-runtime*" /T /F >nul 2>&1
)

if /i "%~1"=="--keep-db" goto :done
echo [3/3] PostgreSQL...
"%PY%" scripts\wait_port.py 127.0.0.1 5432 1 >nul 2>&1 || (echo       tidak berjalan & goto :done)
rem script bawaan PortableDev (pg_ctl stop -m fast); "< nul" melewati pause
call "%PG_STOP%" < nul

:done
echo Selesai.
exit /b 0
