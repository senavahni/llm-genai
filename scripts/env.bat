@echo off
rem Siapkan environment tanpa `conda activate`. Dipanggil oleh semua script lain: call "%~dp0env.bat"
set "CONDA_ENV=D:\Data.Fahrul\.conda\envs\llm-genai"
set "PY=%CONDA_ENV%\python.exe"
rem Library\bin wajib agar DLL (OpenVINO, numpy, openssl) termuat
set "PATH=%CONDA_ENV%;%CONDA_ENV%\Library\mingw-w64\bin;%CONDA_ENV%\Library\usr\bin;%CONDA_ENV%\Library\bin;%CONDA_ENV%\Scripts;%PATH%"
set "PG_START=D:\Data.Fahrul\Documents\PortableDev\start-postgres.bat"
set "PG_STOP=D:\Data.Fahrul\Documents\PortableDev\stop-postgres.bat"
set "GIT_CMD=D:\Data.Fahrul\Documents\PortableDev\Git\git-cmd.exe"
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHONUTF8=1"
set "HF_HOME=%PROJECT_ROOT%\local_models\hf_cache"
cd /d "%PROJECT_ROOT%"
rem muat variabel dari .env (baris non-komentar KEY=VALUE; jangan pakai komentar di akhir baris)
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
