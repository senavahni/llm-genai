@echo off
rem Backup DB gateway ke backups\ (7 terakhir). Opsi: --verify (restore uji ke llm_gateway_test)
rem PG_BIN dapat di-override di .env bila PostgreSQL portable ada di lokasi lain.
call "%~dp0env.bat"
"%PY%" scripts\backup_db.py %*
