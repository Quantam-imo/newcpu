# mt5_upload_to_mcl.ps1
# Runs on Windows. Watches MT5 Files folder and POSTs XAUUSD_feed_latest.csv
# to the AstroQuant MCL backend every 2 seconds.
#
# USAGE:
#   powershell -ExecutionPolicy Bypass -File mt5_upload_to_mcl.ps1
#
# --- AUTO-CONFIGURED ---
# Auto-resolve backend URL: env var > tunnel_url.txt > static fallback
$_tunnelFile = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "data\tunnel_url.txt"
if ($env:AQ_BACKEND_URL) {
    $_baseUrl = $env:AQ_BACKEND_URL.TrimEnd("/")
} elseif (Test-Path $_tunnelFile) {
    $_baseUrl = (Get-Content $_tunnelFile -Raw).Trim().TrimEnd("/")
} else {
    $_baseUrl = "https://pat-med-integrated-ellis.trycloudflare.com"
}
$MCL_URL = "$_baseUrl/market_causality/mt5_upload?symbol=XAUUSD&timeframe=5m"

# Auto-detect MT5 files folder across common install locations
$MT5_CANDIDATES = @(
    "$env:APPDATA\MetaQuotes\Terminal\Common\Files\XAUUSD_feed_latest.csv",
    "C:\Users\$env:USERNAME\AppData\Roaming\MetaQuotes\Terminal\Common\Files\XAUUSD_feed_latest.csv"
)
# Also search all MT5 terminal data folders
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal" -ErrorAction SilentlyContinue | ForEach-Object {
    $MT5_CANDIDATES += "$($_.FullName)\MQL5\Files\XAUUSD_feed_latest.csv"
}

$MT5_FILE = $null
foreach ($c in $MT5_CANDIDATES) {
    if (Test-Path $c) { $MT5_FILE = $c; break }
}
if (-not $MT5_FILE) {
    Write-Host "[mt5-upload] WARN: XAUUSD_feed_latest.csv not found yet. Will keep checking..."
    $MT5_FILE = $MT5_CANDIDATES[0]  # use default, will warn each loop until EA creates it
}

$INTERVAL_SEC = 2
$prev_hash = ""

Write-Host "[mt5-upload] Starting. Watching: $MT5_FILE"
Write-Host "[mt5-upload] Uploading to:        $MCL_URL"
Write-Host "[mt5-upload] Interval: ${INTERVAL_SEC}s  (Ctrl+C to stop)"
Write-Host ""

while ($true) {
    try {
        # Re-scan for file if not found yet
        if (-not (Test-Path $MT5_FILE)) {
            foreach ($c in $MT5_CANDIDATES) {
                if (Test-Path $c) { $MT5_FILE = $c; Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Found MT5 file: $MT5_FILE"; break }
            }
        }
        if (-not (Test-Path $MT5_FILE)) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] WAIT: EA not writing yet. Attach EA to XAUUSD M5 and enable Algo Trading."
        } else {
            $hash = (Get-FileHash $MT5_FILE -Algorithm MD5).Hash
            if ($hash -ne $prev_hash) {
                $response = Invoke-RestMethod `
                    -Uri $MCL_URL `
                    -Method POST `
                    -InFile $MT5_FILE `
                    -ContentType "text/csv"
                $bytes   = $response.bytes
                $ts      = $response.ts
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] uploaded bytes=$bytes ts=$ts"
                $prev_hash = $hash
            }
        }
    } catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: $_"
    }
    Start-Sleep -Seconds $INTERVAL_SEC
}
