@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM AstroQuant Windows startup launcher
REM Starts backend, starts trading engine via API, opens dashboard, and launches watchdog.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"
set "WORKSPACE_DIR=%ASTROQUANT_DIR%\.."
set "PYTHON_EXE=%WORKSPACE_DIR%\.venv\Scripts\python.exe"
set "ALT_PYTHON_EXE=%WORKSPACE_DIR%\..\.venv\Scripts\python.exe"
set "HOST=127.0.0.1"
set "PORT=8000"
set "BASE_URL=http://%HOST%:%PORT%"
set "LOG_DIR=%WORKSPACE_DIR%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] AstroQuant directory: %ASTROQUANT_DIR%
echo [INFO] Workspace directory: %WORKSPACE_DIR%

if not exist "%PYTHON_EXE%" (
  if exist "%ALT_PYTHON_EXE%" (
    set "PYTHON_EXE=%ALT_PYTHON_EXE%"
  ) else (
    echo [ERROR] Python not found.
    echo [HINT] Checked: %PYTHON_EXE%
    echo [HINT] Checked: %ALT_PYTHON_EXE%
    pause
    exit /b 1
  )
)

cd /d "%ASTROQUANT_DIR%"

echo [INFO] Launching backend on %BASE_URL% ...
start "AstroQuant Backend" cmd /k "\"%PYTHON_EXE%\" -m uvicorn backend.main:app --host %HOST% --port %PORT% --log-level info"

set /a TRIES=0
:wait_backend
set /a TRIES+=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%BASE_URL%/status' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL% EQU 0 goto backend_ready

if %TRIES% GEQ 40 (
  echo [ERROR] Backend did not become healthy in time.
  echo [HINT] Check backend window logs.
  pause
  exit /b 1
)

echo [INFO] Waiting for backend ... (%TRIES%/40)
timeout /t 2 /nobreak >nul
goto wait_backend

:backend_ready
echo [OK] Backend is healthy.

echo [INFO] Starting MultiSymbolRunner via /engine/start ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Method Post -Uri '%BASE_URL%/engine/start' -TimeoutSec 10 | Out-Null; exit 0 } catch { exit 1 }"
if %ERRORLEVEL% NEQ 0 (
  echo [WARN] Engine start request failed. You can retry manually:
  echo        curl -X POST %BASE_URL%/engine/start
) else (
  echo [OK] Engine start requested.
)

if exist "%ASTROQUANT_DIR%\watchdog_astroquant.ps1" (
  echo [INFO] Launching watchdog monitor ...
  start "AstroQuant Watchdog" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%ASTROQUANT_DIR%\watchdog_astroquant.ps1"
) else (
  echo [WARN] watchdog_astroquant.ps1 not found; skipping watchdog.
)

echo [INFO] Opening dashboard ...
start "AstroQuant Dashboard" "%BASE_URL%"

echo [DONE] AstroQuant startup sequence completed.
exit /b 0
