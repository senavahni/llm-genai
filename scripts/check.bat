@echo off
rem Gerbang kualitas (TASK-20): lint, format, tipe, test + coverage, secret scan.
rem Berhenti di langkah pertama yang gagal. PostgreSQL harus hidup (test integrasi).
call "%~dp0env.bat"

echo [1/6] ruff check
ruff check . || exit /b 1
echo [2/6] ruff format --check
ruff format --check . || exit /b 1
echo [3/6] mypy app runtime
mypy app runtime || exit /b 1
echo [4/6] pytest + coverage
"%PY%" -m pytest -q --cov=app --cov=runtime --cov-report= || exit /b 1
echo [5/6] coverage minimal 70%% per paket
for %%P in (app/services app/utils runtime/device runtime/services) do (
  "%PY%" -m coverage report --include="%%P/*" --fail-under=70 >nul || (
    echo coverage %%P di bawah 70%%:
    "%PY%" -m coverage report --include="%%P/*"
    exit /b 1
  )
)
"%PY%" -m coverage report --include="app/services/*,app/utils/*,runtime/device/*,runtime/services/*" | findstr TOTAL
echo [6/6] secret scan (logs + DB dev + DB uji)
"%PY%" scripts\secret_scan.py --db both || exit /b 1

echo CHECK OK
