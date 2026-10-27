@echo off
call "%~dp0env.bat"
"%PY%" -m alembic upgrade head
