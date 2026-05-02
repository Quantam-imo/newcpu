param(
  [string]$RepoRoot = "$PSScriptRoot\..",
  [string]$UploaderTaskName = "AstroQuant-MT5-GHCP",
  [int]$MaxLagMinutes = 10
)

$ErrorActionPreference = "Stop"

$repoResolved = [System.IO.Path]::GetFullPath($RepoRoot)
$checkScript = Join-Path $repoResolved "windows\check_mt5_ghcp_freshness.ps1"
$recoveryLog = "$env:ProgramData\AstroQuant\logs\mt5_ghcp_recovery.log"

$logDir = Split-Path -Parent $recoveryLog
if (-not (Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

if (-not (Test-Path $checkScript)) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR missing health script: $checkScript"
  Add-Content -Path $recoveryLog -Value $msg
  Write-Host $msg
  exit 2
}

# Run freshness check. Non-zero means stale/missing and should trigger recovery.
& $checkScript -MaxLagMinutes $MaxLagMinutes
$checkExit = $LASTEXITCODE

if ($checkExit -eq 0) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] OK no recovery needed"
  Add-Content -Path $recoveryLog -Value $msg
  Write-Host $msg
  exit 0
}

$msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] WARN stale feed detected (health_exit=$checkExit), restarting task=$UploaderTaskName"
Add-Content -Path $recoveryLog -Value $msg
Write-Host $msg

# Stop then start uploader task to force a clean loop restart.
schtasks /End /TN $UploaderTaskName *> $null
Start-Sleep -Seconds 2
schtasks /Run /TN $UploaderTaskName *> $null

$done = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ACTION recovery restart issued for task=$UploaderTaskName"
Add-Content -Path $recoveryLog -Value $done
Write-Host $done
exit 0
