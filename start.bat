@echo off
rem Launcher satu klik: PostgreSQL -> aktivasi conda env llm-genai -> migrasi -> (runtime lokal) -> gateway.
rem Opsi diteruskan ke scripts\start-all.bat, mis.:
rem   start.bat --no-runtime   hanya provider remote (OpenAI dkk), tanpa model lokal GPU/NPU: start paling cepat
rem   start.bat --lan          gateway bind 0.0.0.0 agar bisa diakses dari mesin lain
setlocal
set "CONDA_ROOT=D:\Miniconda3"
set "CONDA_ENV=D:\Data.Fahrul\.conda\envs\llm-genai"
cd /d "%~dp0"

if not exist ".env" (
  echo .env belum ada. Salin .env.example ke .env lalu isi nilainya.
  goto :end
)

echo [0/2] Aktivasi conda env llm-genai...
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%" || goto :fail
call conda activate "%CONDA_ENV%" || goto :fail

rem start-all.bat: cek/start PostgreSQL (start-postgres.bat portable), migrasi, runtime, gateway
call "scripts\start-all.bat" %*
if errorlevel 1 goto :fail

echo.
echo Selesai. Stop semua: scripts\stop-all.bat --keep-db  ^(tanpa --keep-db ikut mematikan PostgreSQL^)
goto :end

:fail
echo.
echo GAGAL - lihat pesan di atas dan folder logs\

:end
echo.
pause
endlocal
