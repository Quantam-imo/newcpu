param(
  [string]$TaskName = "AstroQuant-MT5-GHCP-Health",
  [string]$RepoRoot = "$PSScriptRoot\..",
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
$checkScript = Join-Path $repoResolved "windows\check_mt5_ghcp_freshness.ps1"
if (-not (Test-Path $checkScript)) { throw "Health check script not found: $checkScript" }

$taskActionCmd = "powershell.exe"
$taskActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$checkScript`" -MaxLagMinutes $MaxLagMinutes"

schtasks /Query /TN $TaskName *> $null
if ($LASTEXITCODE -eq 0) {
  schtasks /Delete /TN $TaskName /F | Out-Null
}

schtasks /Create /F /TN $TaskName /SC MINUTE /MO $CheckEveryMinutes /RL HIGHEST /TR "$taskActionCmd $taskActionArgs" | Out-Null

Write-Host "Installed health task: $TaskName"
Write-Host "Command: $taskActionCmd $taskActionArgs"
Write-Host "Frequency: every $CheckEveryMinutes minute(s)"
Write-Host "Freshness threshold: $MaxLagMinutes minute(s)"
Write-Host "Run now: schtasks /Run /TN `"$TaskName`""
Write-Host "Alerts: $env:ProgramData\AstroQuant\logs\mt5_ghcp_alert.log"
