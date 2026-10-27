@echo off
rem Supervisor sederhana: restart runtime bila keluar dengan kode != 0 (crash native/OOM driver).
rem Maks 5 restart beruntun; penghitung di-reset bila runtime sempat hidup >= 10 menit.
call "%~dp0env.bat"
set /a N=0
:loop
for /f %%t in ('"%PY%" -c "import time;print(int(time.time()))"') do set /a T0=%%t
"%PY%" scripts\run_runtime.py
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto :eof
for /f %%t in ('"%PY%" -c "import time;print(int(time.time()))"') do set /a T1=%%t
set /a DT=T1-T0
if %DT% GEQ 600 set /a N=0
set /a N+=1
echo %DATE% %TIME% runtime exit %RC% setelah %DT% detik, restart #%N%>>"%PROJECT_ROOT%\logs\runtime-supervisor.log"
if %N% GTR 5 (
  echo %DATE% %TIME% menyerah setelah 5 restart beruntun>>"%PROJECT_ROOT%\logs\runtime-supervisor.log"
  exit /b %RC%
)
timeout /t 5 /nobreak >nul
goto loop
