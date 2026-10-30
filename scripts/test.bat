@echo off
rem Jalankan pytest (unit + integrasi + contract). Argumen diteruskan, contoh:
rem   scripts\test.bat tests\unit -q
rem   scripts\test.bat tests\load --load -s      (load test, menit-an)
rem   scripts\test.bat tests\live --live         (provider remote asli lewat gateway berjalan)
call "%~dp0env.bat"
"%PY%" -m pytest %*
