@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM AstroQuant Windows startup launcher
REM Starts backend, starts trading engine via API, opens dashboard, and launches watchdog.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"
for %%I in ("%ASTROQUANT_DIR%\..") do set "WORKSPACE_DIR=%%~fI"
set "HOST=127.0.0.1"
set "PORT=8000"
set "BASE_URL=http://%HOST%:%PORT%"
set "LOG_DIR=%WORKSPACE_DIR%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [INFO] AstroQuant directory: %ASTROQUANT_DIR%
echo [INFO] Workspace directory: %WORKSPACE_DIR%

REM --- Bootstrap venv if missing ---
set "VENV_DIR=%WORKSPACE_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQS=%WORKSPACE_DIR%\requirements.txt"

if not exist "%PYTHON_EXE%" (
  echo [INFO] No .venv found. Creating virtual environment ...
  where python >nul 2>&1
  if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Python not found on PATH. Install Python 3.11+ and re-run.
    pause
    exit /b 1
  )
  python -m venv "%VENV_DIR%"
  if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
  )
  echo [OK] Virtual environment created.
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python not found in .venv. Please delete .venv and re-run.
  pause
  exit /b 1
)

if exist "%REQS%" (
  echo [INFO] Installing/verifying Python dependencies ...
  "%PYTHON_EXE%" -m pip install --upgrade pip
  if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] pip upgrade failed.
    pause
    exit /b 1
  )
  "%PYTHON_EXE%" -m pip install --quiet -r "%REQS%"
  if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] pip install failed. Check internet connection and retry.
    pause
    exit /b 1
  )
  echo [OK] Dependencies ready.
) else (
  echo [WARN] requirements.txt not found at %REQS% - skipping dep check.
)

echo [INFO] Using Python: %PYTHON_EXE%

cd /d "%ASTROQUANT_DIR%"

echo [INFO] Stopping stale backend processes if present ...
REM Kill any process listening on the configured API port first.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$conns = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($conns) { $conns | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} } }"
REM Kill known uvicorn launch variants used by this project.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and (($_.CommandLine -like '*uvicorn backend.main:app*') -or ($_.CommandLine -like '*uvicorn astroquant.backend.main:app*') -or ($_.CommandLine -like '*python*backend\\main.py*') -or ($_.CommandLine -like '*python*astroquant\\backend\\main.py*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul

echo [INFO] Launching backend on %BASE_URL% ...
start "AstroQuant Backend" cmd /k ""%PYTHON_EXE%" -m uvicorn backend.main:app --host %HOST% --port %PORT% --log-level info"

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
