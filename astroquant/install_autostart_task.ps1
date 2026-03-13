$ErrorActionPreference = "Stop"

param(
    [string]$TaskName = "AstroQuant Auto Start",
    [int]$DelaySeconds = 20
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatchPath = Join-Path $ScriptDir "start_astroquant.bat"

if (-not (Test-Path $BatchPath)) {
    throw "start_astroquant.bat not found at $BatchPath"
}

$triggerDelay = "PT${DelaySeconds}S"

$action = New-ScheduledTaskAction -Execute $BatchPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = $triggerDelay

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -RunLevel Highest -LogonType InteractiveToken

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Task '$TaskName' installed successfully."
Write-Host "Startup script: $BatchPath"
Write-Host "Trigger delay: $DelaySeconds seconds"
Write-Host "User: $currentUser"
