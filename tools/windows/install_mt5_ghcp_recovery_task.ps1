param(
  [string]$TaskName = "AstroQuant-MT5-GHCP-Recovery",
  [string]$RepoRoot = "$PSScriptRoot\..",
  [string]$UploaderTaskName = "AstroQuant-MT5-GHCP",
  [int]$MaxLagMinutes = 10,
  [int]$CheckEveryMinutes = 5
)

$ErrorActionPreference = "Stop"

if ($CheckEveryMinutes -lt 1) {
  throw "CheckEveryMinutes must be >= 1"
}
if ($MaxLagMinutes -lt 1) {
  throw "MaxLagMinutes must be >= 1"
}

$repoResolved = [System.IO.Path]::GetFullPath($RepoRoot)
$recoveryScript = Join-Path $repoResolved "windows\recover_mt5_ghcp_if_stale.ps1"
if (-not (Test-Path $recoveryScript)) { throw "Recovery script not found: $recoveryScript" }

$taskActionCmd = "powershell.exe"
$taskActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$recoveryScript`" -UploaderTaskName `"$UploaderTaskName`" -MaxLagMinutes $MaxLagMinutes"

schtasks /Query /TN $TaskName *> $null
if ($LASTEXITCODE -eq 0) {
  schtasks /Delete /TN $TaskName /F | Out-Null
}

schtasks /Create /F /TN $TaskName /SC MINUTE /MO $CheckEveryMinutes /RL HIGHEST /TR "$taskActionCmd $taskActionArgs" | Out-Null

Write-Host "Installed recovery task: $TaskName"
Write-Host "Command: $taskActionCmd $taskActionArgs"
Write-Host "Frequency: every $CheckEveryMinutes minute(s)"
Write-Host "Freshness threshold: $MaxLagMinutes minute(s)"
Write-Host "Run now: schtasks /Run /TN `"$TaskName`""
Write-Host "Recovery log: $env:ProgramData\AstroQuant\logs\mt5_ghcp_recovery.log"
