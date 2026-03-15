@echo off
setlocal EnableExtensions

REM AstroQuant Windows shutdown helper

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"
set "HOST=127.0.0.1"
set "PORT=8000"
set "BASE_URL=http://%HOST%:%PORT%"

cd /d "%ASTROQUANT_DIR%"

echo [INFO] Requesting engine stop via API ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Method Post -Uri '%BASE_URL%/engine/stop' -TimeoutSec 10 | Out-Null; exit 0 } catch { exit 1 }"
if %ERRORLEVEL% EQU 0 (
  echo [OK] Engine stop requested.
) else (
  echo [WARN] Engine stop API request failed (backend may already be down).
)

echo [INFO] Stopping watchdog PowerShell process ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*watchdog_astroquant.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo [INFO] Stopping backend process(es) ...
REM Kill any process listening on the configured API port first.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$conns = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($conns) { $conns | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} } }"
REM Kill known uvicorn launch variants used by this project.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and (($_.CommandLine -like '*uvicorn backend.main:app*') -or ($_.CommandLine -like '*uvicorn astroquant.backend.main:app*') -or ($_.CommandLine -like '*python*backend\\main.py*') -or ($_.CommandLine -like '*python*astroquant\\backend\\main.py*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo [DONE] AstroQuant stop sequence completed.
exit /b 0
