@echo off
setlocal EnableExtensions

REM One-click Windows setup for AstroQuant auto-start.
REM 1) Installs Task Scheduler autostart task
REM 2) Starts AstroQuant immediately

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"

cd /d "%ASTROQUANT_DIR%"

echo [INFO] Installing Task Scheduler autostart task ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ASTROQUANT_DIR%\install_autostart_task.ps1" -TaskName "AstroQuant Auto Start" -DelaySeconds 20
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Task installation failed.
  echo [HINT] Re-run this file using Administrator privileges.
  pause
  exit /b 1
)

echo [OK] Task installed.

echo [INFO] Starting AstroQuant now ...
call "%ASTROQUANT_DIR%\start_astroquant.bat"
if %ERRORLEVEL% NEQ 0 (
  echo [WARN] Startup script reported an issue. Check backend/watchdog windows.
) else (
  echo [OK] Startup script completed.
)

echo [DONE] Auto-setup finished.
exit /b 0
