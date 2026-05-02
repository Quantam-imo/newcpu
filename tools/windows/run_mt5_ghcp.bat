@echo off
setlocal enableextensions

REM Launcher for mt5_auto_export_via_ghcp.py
REM Configure these env vars once in the task or system env:
REM   AQ_PYTHON            (optional, default: py -3)
REM   AQ_SCRIPT            (optional, absolute path to mt5_auto_export_via_ghcp.py)
REM   AQ_CODESPACE_NAME    (optional)
REM   AQ_REMOTE_DROP_DIR   (optional)
REM   AQ_SYMBOL            (optional)
REM   AQ_BARS              (optional)
REM   AQ_INTERVAL_SECONDS  (optional)

if "%AQ_PYTHON%"=="" set "AQ_PYTHON=py -3"
if "%AQ_SCRIPT%"=="" set "AQ_SCRIPT=%~dp0..\mt5_auto_export_via_ghcp.py"

set "AQ_LOG_DIR=%ProgramData%\AstroQuant\logs"
if not exist "%AQ_LOG_DIR%" mkdir "%AQ_LOG_DIR%" >nul 2>&1
set "AQ_LOG_FILE=%AQ_LOG_DIR%\mt5_ghcp_uploader.log"

echo [%date% %time%] Starting MT5 GHCP uploader >> "%AQ_LOG_FILE%"
%AQ_PYTHON% "%AQ_SCRIPT%" >> "%AQ_LOG_FILE%" 2>&1
set "ERR=%ERRORLEVEL%"
echo [%date% %time%] MT5 GHCP uploader exited code=%ERR% >> "%AQ_LOG_FILE%"
exit /b %ERR%
