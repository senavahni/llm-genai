@echo off
rem Mode B: stack lengkap (start-all.bat) dengan gateway di belakang Traefik.
rem Gateway tetap bind 127.0.0.1:8000; pintu masuk dari luar hanya Traefik :8080.
rem Opsi diteruskan ke start-all.bat (mis. --no-runtime).
setlocal
call "%~dp0env.bat"
call "%~dp0start-all.bat" --behind-proxy %* || exit /b 1

echo [6/6] Traefik...
"%PY%" scripts\wait_port.py 127.0.0.1 8080 1 >nul 2>&1 && (echo       sudah berjalan) || (
  start "traefik" /min cmd /c ""%~dp0start-traefik.bat""
)
rem /health/live: siap begitu Traefik meneruskan ke gateway (healthcheck service tiap 10 detik)
"%PY%" scripts\healthcheck.py http://127.0.0.1:8080/health/live 60 || (
  echo GAGAL - cek logs\traefik.log
  exit /b 1
)
echo Traefik siap: http://127.0.0.1:8080  (dashboard http://127.0.0.1:8081/dashboard/)
exit /b 0
