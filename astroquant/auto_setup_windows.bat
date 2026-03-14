@echo off
setlocal EnableExtensions

REM One-click Windows setup for AstroQuant auto-start.
REM 1) Installs Task Scheduler autostart task
REM 2) Starts AstroQuant immediately

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"
set "INSTALL_PS1=%ASTROQUANT_DIR%\install_autostart_task.ps1"
set "START_BAT=%ASTROQUANT_DIR%\start_astroquant.bat"

cd /d "%ASTROQUANT_DIR%"

if not exist "%INSTALL_PS1%" (
  echo [ERROR] Missing installer script: %INSTALL_PS1%
  pause
  exit /b 1
)

if not exist "%START_BAT%" (
  echo [ERROR] Missing startup script: %START_BAT%
  pause
  exit /b 1
)

echo [INFO] Installing Task Scheduler autostart task ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_PS1%"
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Task installation failed.
  echo [HINT] Check install_autostart_task.ps1 syntax and run as Administrator.
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
