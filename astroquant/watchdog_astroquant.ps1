$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AstroQuantDir = (Resolve-Path $ScriptDir).Path
$WorkspaceDir = (Resolve-Path (Join-Path $AstroQuantDir "..")).Path
$PythonExe = Join-Path $WorkspaceDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $WorkspaceDir "logs"
$LogFile = Join-Path $LogDir "watchdog.log"

$HostIp = "127.0.0.1"
$Port = 8000
$BaseUrl = "http://$HostIp`:$Port"
$StatusUrl = "$BaseUrl/status"
$EngineStartUrl = "$BaseUrl/engine/start"
$EngineStopUrl = "$BaseUrl/engine/stop"
$TelegramTestUrl = "$BaseUrl/telegram/test"

$Global:AlertCooldownSec = 300
$Global:LastAlertAt = [datetime]::MinValue

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

function Write-Log {
    param([string]$Level, [string]$Message)
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$stamp [$Level] $Message" | Out-File -FilePath $LogFile -Encoding UTF8 -Append
}

function Send-RecoveryAlert {
    param([string]$Event, [string]$Detail)

    $now = Get-Date
    $elapsed = ($now - $Global:LastAlertAt).TotalSeconds
    if ($elapsed -lt $Global:AlertCooldownSec) {
        Write-Log "INFO" "Alert suppressed due to cooldown ($([int]$elapsed)s). Event: $Event"
        return
    }

    $msg = "AstroQuant watchdog recovery: $Event`n$Detail`nTime: $($now.ToString('yyyy-MM-dd HH:mm:ss'))"
    try {
        $payload = @{ message = $msg } | ConvertTo-Json -Depth 3
        Invoke-RestMethod -Method Post -Uri $TelegramTestUrl -Body $payload -ContentType "application/json" -TimeoutSec 10 | Out-Null
        $Global:LastAlertAt = $now
        Write-Log "INFO" "Recovery alert sent to Telegram endpoint. Event: $Event"
    }
    catch {
        Write-Log "WARN" "Failed to send Telegram recovery alert: $($_.Exception.Message)"
    }
}

function Ensure-Backend {
    if (-not (Test-Path $PythonExe)) {
        Write-Log "ERROR" "Python executable not found at $PythonExe"
        return $false
    }

    $running = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*uvicorn backend.main:app*"
    }

    if ($running) {
        return $false
    }

    Write-Log "WARN" "Backend process missing. Restarting uvicorn."
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$PythonExe`" -m uvicorn backend.main:app --host $HostIp --port $Port --log-level info" -WorkingDirectory $AstroQuantDir | Out-Null
    Start-Sleep -Seconds 4
    return $true
}

function Ensure-Engine {
    param([bool]$ForceAlert = $false)

    try {
        $resp = Invoke-RestMethod -Method Post -Uri $EngineStartUrl -TimeoutSec 10
        $statusText = ""
        if ($null -ne $resp -and $resp.PSObject.Properties.Name -contains "status") {
            $statusText = [string]$resp.status
        }
        Write-Log "INFO" "Engine start check sent to /engine/start (status='$statusText')"

        if ($ForceAlert -or ($statusText -eq "Engine Started")) {
            Send-RecoveryAlert -Event "Engine Restart" -Detail "Engine start requested by watchdog."
        }
    }
    catch {
        Write-Log "WARN" "Engine start request failed: $($_.Exception.Message)"
    }
}

Write-Log "INFO" "Watchdog started. Monitoring AstroQuant every 60 seconds."

while ($true) {
    try {
        $backendRestarted = Ensure-Backend
        if ($backendRestarted) {
            Send-RecoveryAlert -Event "Backend Restart" -Detail "uvicorn backend process was missing and restarted."
        }

        try {
            $status = Invoke-WebRequest -UseBasicParsing -Uri $StatusUrl -TimeoutSec 5
            if ($status.StatusCode -eq 200) {
                Write-Log "INFO" "Backend healthy (200)."
                Ensure-Engine -ForceAlert:$backendRestarted
            }
            else {
                Write-Log "WARN" "Backend status code was $($status.StatusCode)."
            }
        }
        catch {
            Write-Log "WARN" "Status check failed. $($_.Exception.Message)"
        }
    }
    catch {
        Write-Log "ERROR" "Unexpected watchdog error: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 60
}
