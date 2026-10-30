@echo off
rem Benchmark model lokal (NF11) lewat gateway yang berjalan; tabel ditulis ke docs\perf-report.md.
rem Butuh LGW_TEST_KEY (key client dengan akses local/*). Contoh:
rem   scripts\bench.bat --runs 3 --fim-runs 20
rem   scripts\bench.bat --only local/qwen2.5-7b --no-report
call "%~dp0env.bat"
"%PY%" tests\bench\bench_local.py %*
