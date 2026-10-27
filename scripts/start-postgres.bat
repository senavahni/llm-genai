@echo off
call "%~dp0env.bat"
rem `< nul` melewati `pause` di script PostgreSQL portable
call "%PG_START%" < nul
rem tunggu port 5432 siap (maks 30 detik)
"%PY%" scripts\wait_port.py 127.0.0.1 5432 30 || (echo PostgreSQL tidak siap & exit /b 1)
