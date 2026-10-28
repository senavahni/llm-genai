@echo off
rem Jalankan perintah di dalam Anaconda Prompt (miniconda3) dengan env llm-genai aktif.
rem Contoh: scripts\conda-run.bat python scripts\download_models.py --dry-run
set "CONDA_ROOT=D:\Miniconda3"
set "CONDA_ENV=D:\Data.Fahrul\.conda\envs\llm-genai"
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%" || exit /b 1
call conda activate "%CONDA_ENV%" || exit /b 1
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "HF_HOME=%CD%\local_models\hf_cache"
set "OV_CACHE_DIR=%CD%\local_models\ov_cache"
rem transfer Xet macet di jaringan ini; pakai HTTPS biasa
if not defined HF_HUB_DISABLE_XET set "HF_HUB_DISABLE_XET=1"
%*
