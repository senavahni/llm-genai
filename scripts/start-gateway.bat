@echo off
call "%~dp0env.bat"
rem access log bawaan uvicorn dimatikan; diganti logs\access.log dari middleware
"%PY%" -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --reload --reload-dir app --no-access-log
