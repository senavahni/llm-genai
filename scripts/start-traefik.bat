@echo off
rem Traefik portable (Mode B). Lokasi binary dapat di-override lewat TRAEFIK_EXE di .env.
call "%~dp0env.bat"
if "%TRAEFIK_EXE%"=="" set "TRAEFIK_EXE=D:\Data.Fahrul\Documents\PortableDev\traefik\traefik.exe"
if not exist "%TRAEFIK_EXE%" (
  echo traefik.exe tidak ditemukan: %TRAEFIK_EXE% - lihat docs\deployment.md Mode B
  exit /b 1
)
"%TRAEFIK_EXE%" --configFile="%PROJECT_ROOT%\deploy\traefik\traefik.yml"
