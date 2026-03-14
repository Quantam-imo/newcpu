$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AstroQuantDir = (Resolve-Path $ScriptDir).Path
$WorkspaceDir = (Resolve-Path (Join-Path $AstroQuantDir "..")).Path
$PythonExe = Join-Path $WorkspaceDir ".venv\Scripts\python.exe"
$AltPythonExe = Join-Path (Join-Path $WorkspaceDir "..") ".venv\Scripts\python.exe"
$LogDir = Join-Path $WorkspaceDir "logs"
$LogFile = Join-Path $LogDir "watchdog.log"

$HostIp = "127.0.0.1"
$Port = 8000
$BaseUrl = "http://$HostIp`:$Port"
$StatusUrl = "$BaseUrl/status"
$ExecutionStatusUrl = "$BaseUrl/status/execution"
$EngineStartUrl = "$BaseUrl/engine/start"
$EngineStopUrl = "$BaseUrl/engine/stop"
$ExecutionReconnectUrl = "$BaseUrl/execution/reconnect?force=true"
$TelegramStatusUrl = "$BaseUrl/telegram/status"
$TelegramTestUrl = "$BaseUrl/telegram/test"

$Global:AlertCooldownSec = 300
$Global:LastAlertAt = [datetime]::MinValue

# Circuit-breaker policy: if a component needs too many recoveries in a short window,
# watchdog pauses further recovery attempts for that component.
$Global:RecoveryPolicy = @{
    "Backend"   = @{ WindowSec = 900; MaxAttempts = 4; CooldownSec = 900 }
    "Engine"    = @{ WindowSec = 900; MaxAttempts = 6; CooldownSec = 600 }
    "Playwright"= @{ WindowSec = 600; MaxAttempts = 6; CooldownSec = 600 }
    "Telegram"  = @{ WindowSec = 600; MaxAttempts = 8; CooldownSec = 300 }
}

$Global:RecoveryState = @{}
foreach ($component in $Global:RecoveryPolicy.Keys) {
    $Global:RecoveryState[$component] = @{
        Attempts = @()
        CooldownUntil = [datetime]::MinValue
    }
}

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

function Test-RecoveryAllowed {
    param([string]$Component)

    if (-not $Global:RecoveryPolicy.ContainsKey($Component)) {
        return @{ Allowed = $true; Reason = "no_policy" }
    }

    $policy = $Global:RecoveryPolicy[$Component]
    $state = $Global:RecoveryState[$Component]
    $now = Get-Date

    if ($now -lt $state.CooldownUntil) {
        $remaining = [int][math]::Ceiling(($state.CooldownUntil - $now).TotalSeconds)
        return @{ Allowed = $false; Reason = ("cooldown_active_" + $remaining + "s") }
    }

    $windowSec = [int]$policy.WindowSec
    $cutoff = $now.AddSeconds(-$windowSec)
    $state.Attempts = @($state.Attempts | Where-Object { $_ -gt $cutoff })

    if ($state.Attempts.Count -ge [int]$policy.MaxAttempts) {
        $state.CooldownUntil = $now.AddSeconds([int]$policy.CooldownSec)
        $state.Attempts = @()
        $Global:RecoveryState[$Component] = $state
        return @{ Allowed = $false; Reason = ("circuit_open_" + [int]$policy.CooldownSec + "s") }
    }

    $Global:RecoveryState[$Component] = $state
    return @{ Allowed = $true; Reason = "ok" }
}

function Register-RecoveryAttempt {
    param([string]$Component)

    if (-not $Global:RecoveryState.ContainsKey($Component)) {
        return
    }

    $state = $Global:RecoveryState[$Component]
    $state.Attempts += (Get-Date)
    $Global:RecoveryState[$Component] = $state
}

function Ensure-Backend {
    if (-not (Test-Path $PythonExe)) {
        if (Test-Path $AltPythonExe) {
            $script:PythonExe = $AltPythonExe
        }
        else {
            Write-Log "ERROR" "Python executable not found at $PythonExe or $AltPythonExe"
            return $false
        }
    }

    $running = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*uvicorn backend.main:app*"
    }

    if ($running) {
        return $false
    }

    $gate = Test-RecoveryAllowed -Component "Backend"
    if (-not $gate.Allowed) {
        Write-Log "WARN" "Backend recovery blocked by circuit-breaker ($($gate.Reason))."
        return $false
    }

    Write-Log "WARN" "Backend process missing. Restarting uvicorn."
    Register-RecoveryAttempt -Component "Backend"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$PythonExe`" -m uvicorn backend.main:app --host $HostIp --port $Port --log-level info" -WorkingDirectory $AstroQuantDir | Out-Null
    Start-Sleep -Seconds 4
    return $true
}

function Ensure-Engine {
    param([bool]$ForceAlert = $false)

    try {
        $gate = Test-RecoveryAllowed -Component "Engine"
        if (-not $gate.Allowed) {
            Write-Log "WARN" "Engine recovery blocked by circuit-breaker ($($gate.Reason))."
            return
        }

        $resp = Invoke-RestMethod -Method Post -Uri $EngineStartUrl -TimeoutSec 10
        $statusText = ""
        if ($null -ne $resp -and $resp.PSObject.Properties.Name -contains "status") {
            $statusText = [string]$resp.status
        }
        Write-Log "INFO" "Engine start check sent to /engine/start (status='$statusText')"

        if ($ForceAlert -or ($statusText -eq "Engine Started")) {
            Register-RecoveryAttempt -Component "Engine"
            Send-RecoveryAlert -Event "Engine Restart" -Detail "Engine start requested by watchdog."
        }
    }
    catch {
        Write-Log "WARN" "Engine start request failed: $($_.Exception.Message)"
    }
}

function Ensure-Playwright {
    try {
        $exec = Invoke-RestMethod -Method Get -Uri $ExecutionStatusUrl -TimeoutSec 10
        $connected = $false
        $statusText = ""
        $heartbeatState = ""

        if ($null -ne $exec) {
            $connected = [bool]$exec.connected
            $statusText = [string]($exec.execution_status)
            $heartbeatState = [string]($exec.browser_heartbeat_status)
        }

        $needsReconnect = (-not $connected) -or ($statusText -in @("DISCONNECTED", "HALTED", "ERROR")) -or ($heartbeatState -eq "STALE")
        if (-not $needsReconnect) {
            return
        }

        $gate = Test-RecoveryAllowed -Component "Playwright"
        if (-not $gate.Allowed) {
            Write-Log "WARN" "Playwright recovery blocked by circuit-breaker ($($gate.Reason))."
            return
        }

        Write-Log "WARN" "Playwright unhealthy (connected=$connected status=$statusText heartbeat=$heartbeatState). Reconnecting."
        Register-RecoveryAttempt -Component "Playwright"
        $reconnectResp = Invoke-RestMethod -Method Post -Uri $ExecutionReconnectUrl -TimeoutSec 20
        $reconnectStatus = ""
        if ($null -ne $reconnectResp -and $reconnectResp.PSObject.Properties.Name -contains "status") {
            $reconnectStatus = [string]$reconnectResp.status
        }
        Write-Log "INFO" "Playwright reconnect response status='$reconnectStatus'"
        Send-RecoveryAlert -Event "Playwright Reconnect" -Detail ("Reconnect triggered (status=" + $reconnectStatus + ")")
    }
    catch {
        Write-Log "WARN" "Playwright recovery failed: $($_.Exception.Message)"
    }
}

function Ensure-Telegram {
    try {
        $tg = Invoke-RestMethod -Method Get -Uri $TelegramStatusUrl -TimeoutSec 10
        $configured = [bool]$tg.configured
        $active = [bool]$tg.active
        $reason = [string]($tg.reason)

        if (-not $configured) {
            Write-Log "INFO" "Telegram not configured; skipping recovery."
            return
        }

        if ($active) {
            return
        }

        $gate = Test-RecoveryAllowed -Component "Telegram"
        if (-not $gate.Allowed) {
            Write-Log "WARN" "Telegram recovery blocked by circuit-breaker ($($gate.Reason))."
            return
        }

        Write-Log "WARN" "Telegram inactive (reason='$reason'). Sending watchdog recovery test."
        $msg = "AstroQuant watchdog: Telegram recovery check"
        $payload = @{ message = $msg } | ConvertTo-Json -Depth 3
        Register-RecoveryAttempt -Component "Telegram"
        $testResp = Invoke-RestMethod -Method Post -Uri $TelegramTestUrl -Body $payload -ContentType "application/json" -TimeoutSec 10
        $ok = $false
        if ($null -ne $testResp -and $testResp.PSObject.Properties.Name -contains "ok") {
            $ok = [bool]$testResp.ok
        }

        if ($ok) {
            Write-Log "INFO" "Telegram recovery test succeeded."
            Send-RecoveryAlert -Event "Telegram Recovery" -Detail "Telegram was inactive and recovered by watchdog test send."
        }
        else {
            Write-Log "WARN" "Telegram recovery test failed."
        }
    }
    catch {
        Write-Log "WARN" "Telegram health check failed: $($_.Exception.Message)"
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
                Ensure-Playwright
                Ensure-Telegram
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
