@echo off
rem Gateway (1 worker). Opsi diteruskan ke run_server.py: --lan, --behind-proxy, --reload (dev)
call "%~dp0env.bat"
if "%APP_ENV%"=="" set "APP_ENV=prod"
"%PY%" scripts\run_server.py %*
