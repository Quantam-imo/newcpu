@echo off
setlocal EnableExtensions

REM One-click Windows setup for AstroQuant auto-start.
REM 1) Installs Task Scheduler autostart task
REM 2) Starts AstroQuant immediately

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "ASTROQUANT_DIR=%%~fI"

cd /d "%ASTROQUANT_DIR%"

echo [INFO] Repairing install_autostart_task.ps1 (self-heal) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Join-Path '%ASTROQUANT_DIR%' 'install_autostart_task.ps1'; $content = @'
$ErrorActionPreference = 'Stop'

param(
  [string]$TaskName = 'AstroQuant Auto Start',
    [int]$DelaySeconds = 20
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatchPath = Join-Path $ScriptDir 'start_astroquant.bat'

if (-not (Test-Path $BatchPath)) {
  throw ('start_astroquant.bat not found at ' + $BatchPath)
}

$triggerDelay = 'PT{0}S' -f $DelaySeconds

$action = New-ScheduledTaskAction -Execute $BatchPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = $triggerDelay

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -RunLevel Highest -LogonType InteractiveToken

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host ('Task ''{0}'' installed successfully.' -f $TaskName)
Write-Host ('Startup script: {0}' -f $BatchPath)
Write-Host ('Trigger delay: {0} seconds' -f $DelaySeconds)
Write-Host ('User: {0}' -f $currentUser)
'@; Set-Content -Path $p -Value $content -Encoding UTF8"
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Failed to repair install_autostart_task.ps1.
  pause
  exit /b 1
)

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
