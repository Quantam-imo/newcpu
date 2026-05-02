param(
  [string]$TaskName = "AstroQuant-MT5-GHCP",
  [string]$RepoRoot = "$PSScriptRoot\..",
  [string]$PythonCommand = "py -3",
  [string]$CodespaceName = "humble-goggles-q7r79pgxw79q245rq",
  [string]$RemoteDropDir = "/workspaces/newcpu/transfer_out/mt5_drop",
  [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "Stop"

$repoResolved = [System.IO.Path]::GetFullPath($RepoRoot)
$launcher = Join-Path $repoResolved "windows\run_mt5_ghcp.bat"
$scriptPath = Join-Path $repoResolved "mt5_auto_export_via_ghcp.py"

if (-not (Test-Path $launcher)) { throw "Launcher not found: $launcher" }
if (-not (Test-Path $scriptPath)) { throw "Uploader script not found: $scriptPath" }

$taskActionCmd = "cmd.exe"
$taskActionArgs = "/c set \"AQ_PYTHON=$PythonCommand\"&& set \"AQ_SCRIPT=$scriptPath\"&& set \"AQ_CODESPACE_NAME=$CodespaceName\"&& set \"AQ_REMOTE_DROP_DIR=$RemoteDropDir\"&& set \"AQ_INTERVAL_SECONDS=$IntervalSeconds\"&& call `\"$launcher`\""

# Create task via schtasks for broad Windows compatibility
schtasks /Query /TN $TaskName *> $null
if ($LASTEXITCODE -eq 0) {
  schtasks /Delete /TN $TaskName /F | Out-Null
}

schtasks /Create /F /TN $TaskName /SC ONLOGON /RL HIGHEST /TR "$taskActionCmd $taskActionArgs" | Out-Null

Write-Host "Installed task: $TaskName"
Write-Host "Command: $taskActionCmd $taskActionArgs"
Write-Host "To run now: schtasks /Run /TN `"$TaskName`""
Write-Host "To stop: taskkill /F /IM python.exe"
Write-Host "Logs: $env:ProgramData\AstroQuant\logs\mt5_ghcp_uploader.log"
