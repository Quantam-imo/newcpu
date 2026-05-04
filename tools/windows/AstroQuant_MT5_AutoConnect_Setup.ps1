param(
    [string]$BackendUrl    = "https://pat-med-integrated-ellis.trycloudflare.com",
    [string]$UploadToken   = "",
    [string]$PythonCommand = "py -3",
    [int]$IntervalSec      = 60,
    [string]$TaskName      = "AstroQuant-MT5-HTTP"
)

$ErrorActionPreference = "Stop"

$installDir  = "$env:ProgramData\AstroQuant"
$logDir      = "$installDir\logs"
$scriptFile  = "$installDir\mt5_auto_export.py"
$launcherBat = "$installDir\run_mt5_upload.bat"

if (-not (Test-Path $installDir)) { New-Item -ItemType Directory -Path $installDir | Out-Null }
if (-not (Test-Path $logDir))     { New-Item -ItemType Directory -Path $logDir     | Out-Null }

Write-Host ""
Write-Host "AstroQuant MT5 Auto-Connect Setup"
Write-Host "=================================="
Write-Host ("Install dir : " + $installDir)
Write-Host ("Backend URL : " + $BackendUrl)
Write-Host ("Interval    : " + $IntervalSec + "s")
Write-Host ""

# ---------- Write Python uploader ----------------------------------------------
$py = @'
import logging, os, sys, time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    sys.exit("ERROR: run:  pip install MetaTrader5 requests")
try:
    import requests
except ImportError:
    sys.exit("ERROR: run:  pip install MetaTrader5 requests")

BACKEND_URL  = os.getenv("AQ_BACKEND_URL", "https://pat-med-integrated-ellis.trycloudflare.com").rstrip("/")
UPLOAD_TOKEN = os.getenv("MCL_MT5_UPLOAD_TOKEN", "").strip()
INTERVAL     = int(os.getenv("AQ_INTERVAL_SECONDS", "60"))
SYMBOL       = os.getenv("AQ_SYMBOL", "XAUUSD")
TF           = mt5.TIMEFRAME_M5
BARS         = 500
ENDPOINT     = "/market_causality/mt5_upload?symbol=" + SYMBOL + "&timeframe=5m"

_log_dir = os.getenv("AQ_LOG_DIR", os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(_log_dir, "mt5_uploader.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("aq_mt5")

def to_csv(rates):
    lines = ["Date;Open;High;Low;Close;TickVolume;Volume;Spread"]
    for r in rates:
        dt = datetime.fromtimestamp(r[0], tz=timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        lines.append(f"{dt};{r[1]:.5f};{r[2]:.5f};{r[3]:.5f};{r[4]:.5f};{int(r[5])};{int(r[7])};{int(r[6])}")
    return "\n".join(lines)

def push(csv):
    hdrs = {"Content-Type": "text/csv"}
    if UPLOAD_TOKEN:
        hdrs["x-mt5-upload-token"] = UPLOAD_TOKEN
    try:
        r = requests.post(BACKEND_URL + ENDPOINT, data=csv.encode(), headers=hdrs, timeout=15)
        if r.status_code == 200:
            j = r.json()
            log.info("OK  rows=%-4s  latest=%s  bytes=%s", j.get("rows","?"), j.get("latest_date","?"), j.get("bytes","?"))
            return True
        log.warning("HTTP %s: %s", r.status_code, r.text[:160])
    except Exception as e:
        log.error("Upload error: %s", e)
    return False

def run():
    log.info("backend=%s  interval=%ds  symbol=%s", BACKEND_URL, INTERVAL, SYMBOL)
    if not mt5.initialize():
        log.error("MT5 initialize() failed: %s", mt5.last_error())
        sys.exit(1)
    log.info("MT5 connected. Export loop running...")
    last_epoch = None
    try:
        while True:
            rates = mt5.copy_rates_from_pos(SYMBOL, TF, 0, BARS)
            if rates is None or len(rates) == 0:
                log.warning("No rates from MT5: %s", mt5.last_error())
            else:
                epoch = int(rates[-1][0])
                ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
                log.info("Pulled %d bars, latest=%s UTC", len(rates), ts)
                if epoch != last_epoch:
                    if push(to_csv(rates)):
                        last_epoch = epoch
                else:
                    log.info("No new candle yet - skipping upload")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        mt5.shutdown()
        log.info("MT5 disconnected.")

if __name__ == "__main__":
    run()
'@

[System.IO.File]::WriteAllText($scriptFile, $py, [System.Text.Encoding]::UTF8)
Write-Host "[1/3] Python uploader written"

# ---------- Write launcher batch -----------------------------------------------
$bat  = "@echo off" + [Environment]::NewLine
$bat += "set AQ_BACKEND_URL=" + $BackendUrl + [Environment]::NewLine
$bat += "set MCL_MT5_UPLOAD_TOKEN=" + $UploadToken + [Environment]::NewLine
$bat += "set AQ_INTERVAL_SECONDS=" + $IntervalSec + [Environment]::NewLine
$bat += "set AQ_LOG_DIR=" + $logDir + [Environment]::NewLine
$bat += $PythonCommand + " " + $scriptFile + " >> " + $logDir + "\mt5_uploader_run.log 2>&1" + [Environment]::NewLine

[System.IO.File]::WriteAllText($launcherBat, $bat, [System.Text.Encoding]::ASCII)
Write-Host "[2/3] Launcher written"

# ---------- Register Task Scheduler --------------------------------------------
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = schtasks /Query /TN $TaskName 2>&1
if ($LASTEXITCODE -eq 0) {
    $null = schtasks /Delete /TN $TaskName /F 2>&1
    Write-Host "      (removed existing task)"
}
$ErrorActionPreference = $prevEAP

$null = schtasks /Create /F /TN $TaskName /SC ONLOGON /RL HIGHEST /TR ('cmd.exe /c "' + $launcherBat + '"') 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "[3/3] Task registered"
} else {
    Write-Warning "Task registration failed - try running PowerShell as Administrator"
}

Write-Host ""
Write-Host "============================================================"
Write-Host " SETUP COMPLETE"
Write-Host "============================================================"
Write-Host (" Script  : " + $scriptFile)
Write-Host (" Launcher: " + $launcherBat)
Write-Host (" Task    : " + $TaskName + "  (runs on every Windows login)")
Write-Host (" Logs    : " + $logDir)
Write-Host ""
Write-Host " To START now (no reboot):"
Write-Host ('   schtasks /Run /TN "' + $TaskName + '"')
Write-Host ""
Write-Host " To check logs:"
Write-Host ('   notepad "' + $logDir + '\mt5_uploader.log"')
Write-Host ""
Write-Host " To UPDATE backend URL when tunnel changes:"
Write-Host "   Re-run this script with -BackendUrl <new-url>"
Write-Host ""
Write-Host " To STOP:"
Write-Host "   taskkill /F /IM python.exe"
Write-Host "============================================================"
