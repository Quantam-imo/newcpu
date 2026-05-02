param(
  [string]$LogFile = "$env:ProgramData\AstroQuant\logs\mt5_ghcp_uploader.log",
  [string]$AlertFile = "$env:ProgramData\AstroQuant\logs\mt5_ghcp_alert.log",
  [int]$MaxLagMinutes = 10
)

$ErrorActionPreference = "Stop"

$logDir = Split-Path -Parent $LogFile
if (-not (Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

if (-not (Test-Path $LogFile)) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] WARN no uploader log found: $LogFile"
  Add-Content -Path $AlertFile -Value $msg
  Write-Host $msg
  exit 2
}

$lines = Get-Content -Path $LogFile -Tail 400
if (-not $lines -or $lines.Count -eq 0) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] WARN uploader log is empty"
  Add-Content -Path $AlertFile -Value $msg
  Write-Host $msg
  exit 2
}

$epoch = $null
for ($i = $lines.Count - 1; $i -ge 0; $i--) {
  $line = $lines[$i]
  if ($line -match "_feed_(\d+)\.csv") {
    $epoch = [int64]$matches[1]
    break
  }
}

if (-not $epoch) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] WARN no successful push marker found in uploader log"
  Add-Content -Path $AlertFile -Value $msg
  Write-Host $msg
  exit 2
}

$nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$lagSec = $nowEpoch - $epoch
$maxLagSec = $MaxLagMinutes * 60
$lastUtc = [DateTimeOffset]::FromUnixTimeSeconds($epoch).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")

if ($lagSec -gt $maxLagSec) {
  $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ALERT stale MT5 push lag=${lagSec}s max=${maxLagSec}s last_candle_utc=$lastUtc"
  Add-Content -Path $AlertFile -Value $msg
  Write-Host $msg
  exit 2
}

$msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] OK MT5 push fresh lag=${lagSec}s max=${maxLagSec}s last_candle_utc=$lastUtc"
Write-Host $msg
exit 0
