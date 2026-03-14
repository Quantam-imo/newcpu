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

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "{0}"' -f $BatchPath)
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
