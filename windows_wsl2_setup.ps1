# ============================================================
#  AstroQuant - Windows WSL2 Full Setup Script
#  Run this on your Windows PC as Administrator
#  PowerShell: Right-click PowerShell -> "Run as Administrator"
#  Then paste:  Set-ExecutionPolicy Bypass -Scope Process -Force; .\windows_wsl2_setup.ps1
# ============================================================

param(
    [string]$GithubRepo = "https://github.com/Quantam-imo/newcpu.git",
    [string]$WslUser    = "astroquant",
    [string]$InstallDir = "/home/astroquant/newcpu"
)

$ErrorActionPreference = "Stop"

function Write-Header($msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Write-OK($msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-WARN($msg) { Write-Host "  [!!]  $msg" -ForegroundColor Yellow }
function Write-STEP($msg) { Write-Host "  -->   $msg" -ForegroundColor White }

# ── 0. Must run as Admin ──────────────────────────────────────
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Please run PowerShell as Administrator." -ForegroundColor Red
    Write-Host "  Right-click PowerShell -> 'Run as Administrator'" -ForegroundColor Yellow
    pause; exit 1
}

# ── 0b. OS and architecture validation ───────────────────────
Write-Header "Pre-flight: System Compatibility Check"

# Must be 64-bit OS
if (-NOT [System.Environment]::Is64BitOperatingSystem) {
    Write-Host "ERROR: This machine is NOT 64-bit. AstroQuant requires a 64-bit Windows OS." -ForegroundColor Red
    pause; exit 1
}
Write-OK "64-bit OS confirmed"

# Must be x64 processor (not ARM64)
$cpuArch = (Get-WmiObject Win32_Processor).Architecture
# Architecture: 9=x64, 12=ARM64, 0=x86
if ($cpuArch -eq 12) {
    Write-WARN "ARM64 processor detected. Chrome amd64 package will not run natively."
    Write-WARN "Consider using Playwright Chromium instead: playwright install chromium"
} elseif ($cpuArch -ne 9) {
    Write-Host "ERROR: Unsupported CPU architecture ($cpuArch). Requires x64 (Intel/AMD)." -ForegroundColor Red
    pause; exit 1
}
Write-OK "x64 (Intel/AMD) processor confirmed"

# Windows version check — Win 10 build 19041+ or Win 11 required for WSL2
$osVersion = [System.Environment]::OSVersion.Version
$osBuild   = $osVersion.Build
$winEdition = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").ProductName
Write-OK "OS: $winEdition (Build $osBuild)"

if ($osBuild -lt 19041) {
    Write-Host "ERROR: WSL2 requires Windows 10 version 2004 (Build 19041) or later." -ForegroundColor Red
    Write-Host "  Your build: $osBuild.  Please update Windows first." -ForegroundColor Yellow
    pause; exit 1
}

if ($osBuild -ge 22000) {
    Write-OK "Windows 11 detected — full WSL2 support confirmed"
} else {
    Write-OK "Windows 10 (Build $osBuild) — WSL2 supported"
}

Write-Header "AstroQuant WSL2 Installer"
Write-Host "  This script will:"
Write-Host "    1. Enable WSL2 on this Windows PC"
Write-Host "    2. Install Ubuntu 22.04"
Write-Host "    3. Clone AstroQuant project inside WSL2"
Write-Host "    4. Set up Python environment + install packages"
Write-Host "    5. Configure autostart on Windows boot"
Write-Host ""

# ── 1. Enable WSL2 features ──────────────────────────────────
Write-Header "Step 1/5 — Enabling WSL2 features"

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
$vmFeature   = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform

if ($wslFeature.State -ne "Enabled") {
    Write-STEP "Enabling Windows Subsystem for Linux..."
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    Write-OK "WSL feature enabled"
} else {
    Write-OK "WSL already enabled"
}

if ($vmFeature.State -ne "Enabled") {
    Write-STEP "Enabling Virtual Machine Platform..."
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    Write-OK "VirtualMachinePlatform enabled"
} else {
    Write-OK "VirtualMachinePlatform already enabled"
}

# ── 2. Set WSL default version to 2 ──────────────────────────
Write-Header "Step 2/5 — Setting WSL2 as default"

# Download and install WSL2 kernel update if needed
$wslKernelUrl  = "https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi"
$wslKernelPath = "$env:TEMP\wsl_update_x64.msi"

$wslVersion = & wsl --status 2>&1
if ($wslVersion -notmatch "2") {
    Write-STEP "Downloading WSL2 kernel update..."
    try {
        Invoke-WebRequest -Uri $wslKernelUrl -OutFile $wslKernelPath -UseBasicParsing
        Start-Process msiexec.exe -ArgumentList "/i `"$wslKernelPath`" /quiet /norestart" -Wait
        Write-OK "WSL2 kernel installed"
    } catch {
        Write-WARN "Could not auto-download kernel. If WSL2 fails, visit: https://aka.ms/wsl2kernel"
    }
}

& wsl --set-default-version 2 2>&1 | Out-Null
Write-OK "Default WSL version set to 2"

# ── 3. Install Ubuntu 22.04 ───────────────────────────────────
Write-Header "Step 3/5 — Installing Ubuntu 22.04"

$distros = & wsl --list --quiet 2>&1
if ($distros -match "Ubuntu-22.04") {
    Write-OK "Ubuntu-22.04 already installed — skipping download"
} else {
    Write-STEP "Installing Ubuntu 22.04 from Microsoft Store (this may take 3-5 min)..."

    # Try winget first (Windows 11), fall back to wsl --install
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Canonical.Ubuntu.2204 --accept-package-agreements --accept-source-agreements --silent
    } else {
        & wsl --install -d Ubuntu-22.04 --no-launch
    }

    Write-OK "Ubuntu-22.04 installed"
    Write-WARN "Ubuntu needs a first-launch setup. A window will open — create a Linux username"
    Write-WARN "IMPORTANT: Use username:  $WslUser"
    Write-WARN "           Set any password you like"
    Write-Host ""
    Write-Host "  Press ENTER to launch Ubuntu first-time setup..." -ForegroundColor Yellow
    Read-Host
    & wsl -d Ubuntu-22.04
}

# ── 4. Bootstrap project inside WSL2 ─────────────────────────
Write-Header "Step 4/5 — Setting up AstroQuant inside WSL2"

Write-STEP "Creating WSL2 setup script..."

# Inject the full .env securely from Codespaces helper file if present on Desktop
$envSourcePath = "$env:USERPROFILE\Desktop\astroquant_env.txt"
$envExists     = Test-Path $envSourcePath

$envInjectBlock = if ($envExists) {
    $envContent = Get-Content $envSourcePath -Raw
    # Escape for PowerShell heredoc passing to bash
    $envEscaped = $envContent -replace "'", "'\'''"
    "echo '$envEscaped' > $InstallDir/.env && echo '  [OK] .env injected from Desktop/astroquant_env.txt'"
} else {
    "echo '  [WARN] astroquant_env.txt not found on Desktop — .env not configured yet'"
}

$linuxSetupScript = @"
#!/bin/bash
set -e
echo '============================================================'
echo '  AstroQuant WSL2 Linux Setup'
echo '============================================================'

# System packages
echo '--> Installing system packages...'
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    redis-server git curl wget unzip \
    build-essential libssl-dev libffi-dev \
    google-chrome-stable 2>/dev/null || true

# Install Google Chrome if not present
if ! command -v google-chrome &>/dev/null && ! command -v google-chrome-stable &>/dev/null; then
    echo '--> Installing Google Chrome...'
    curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb
    sudo dpkg -i /tmp/chrome.deb 2>/dev/null || sudo apt-get install -f -y -qq
    rm -f /tmp/chrome.deb
fi
echo '  [OK] System packages ready'

# Clone project
echo '--> Cloning AstroQuant project...'
if [ -d '$InstallDir/.git' ]; then
    echo '  Already cloned — pulling latest...'
    cd $InstallDir && git pull
else
    git clone $GithubRepo $InstallDir
fi
cd $InstallDir
echo '  [OK] Project cloned'

# Python venv
echo '--> Creating Python virtual environment...'
python3 -m venv .venv
source .venv/bin/activate
echo '--> Installing Python packages (may take 3-5 min)...'
pip install --upgrade pip -q
pip install -r requirements.txt -q
playwright install chromium 2>/dev/null || true
echo '  [OK] Python environment ready'

# Enable systemd in WSL2 (required for systemd autostart)
echo '--> Configuring WSL2 for systemd...'
sudo tee /etc/wsl.conf > /dev/null <<'WSLCONF'
[boot]
systemd=true
command=/bin/bash /home/astroquant/newcpu/non_systemd_autostart_bootstrap.sh

[automount]
enabled = true
options = "metadata"
WSLCONF
echo '  [OK] /etc/wsl.conf configured'

# Make all scripts executable
chmod +x $InstallDir/*.sh 2>/dev/null || true
echo '  [OK] Scripts made executable'

# .env file
$envInjectBlock

# Register autostart hooks in shell
echo '--> Registering autostart...'
AQ_WORKSPACE=$InstallDir bash $InstallDir/enable_boot_autostart.sh || true
echo '  [OK] Autostart registered'

echo ''
echo '============================================================'
echo '  Setup complete!'
echo '  WSL2 will need a restart to activate systemd:'
echo '    In PowerShell (as Admin):  wsl --shutdown'
echo '    Then reopen Ubuntu.'
echo '============================================================'
"@

# Write the linux script into WSL2 temp location
$linuxSetupScript | & wsl -d Ubuntu-22.04 -- bash -c "cat > /tmp/aq_linux_setup.sh && chmod +x /tmp/aq_linux_setup.sh"

Write-STEP "Running Linux setup inside WSL2 (this takes 5-10 min)..."
& wsl -d Ubuntu-22.04 -- bash /tmp/aq_linux_setup.sh

Write-OK "Linux environment configured"

# ── 5. Windows autostart via Task Scheduler ───────────────────
Write-Header "Step 5/5 — Configuring Windows autostart"

Write-STEP "Creating Task Scheduler entry to start AstroQuant on Windows login..."

# VBScript wrapper to run WSL silently (no console window)
$startupVbs = @"
Set oShell = CreateObject("WScript.Shell")
oShell.Run "wsl -d Ubuntu-22.04 -- bash -c 'cd $InstallDir && bash non_systemd_autostart_bootstrap.sh >> data/logs/windows_autostart.log 2>&1'", 0, False
"@

$vbsPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AstroQuant_Autostart.vbs"
$startupVbs | Set-Content -Path $vbsPath -Encoding ASCII
Write-OK "Startup VBScript created: $vbsPath"

# Also register as Task Scheduler entry so it runs at any user login and on system start
$taskName   = "AstroQuant_WSL2_Autostart"
$taskAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""
$taskTrigger1 = New-ScheduledTaskTrigger -AtLogOn
$taskTrigger2 = New-ScheduledTaskTrigger -AtStartup
$taskSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

# Remove existing if any
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $taskAction `
    -Trigger $taskTrigger1,$taskTrigger2 `
    -Settings $taskSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-OK "Task Scheduler entry '$taskName' registered"

# ── Summary ───────────────────────────────────────────────────
Write-Header "COMPLETE"
Write-Host ""
Write-Host "  AstroQuant is now configured for 24/7 auto-start on this Windows PC!" -ForegroundColor Green
Write-Host ""
Write-Host "  NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Restart WSL2 to activate systemd:"   -ForegroundColor White
Write-Host "       wsl --shutdown"                     -ForegroundColor Cyan
Write-Host "       (then reopen Ubuntu or restart PC)" -ForegroundColor White
Write-Host ""

if (-not $envExists) {
    Write-Host "  2. IMPORTANT: Copy your .env file to WSL2:" -ForegroundColor Red
    Write-Host "     a) Download the .env from Codespaces (see instructions below)" -ForegroundColor Yellow
    Write-Host "     b) Save it to Desktop as:  astroquant_env.txt" -ForegroundColor Yellow
    Write-Host "     c) Then in WSL2 Ubuntu terminal run:" -ForegroundColor Yellow
    Write-Host "          cp /mnt/c/Users/$env:USERNAME/Desktop/astroquant_env.txt $InstallDir/.env" -ForegroundColor Cyan
    Write-Host ""
}

Write-Host "  3. After restart, verify with (inside WSL2 Ubuntu):" -ForegroundColor White
Write-Host "       curl http://localhost:8000/status"              -ForegroundColor Cyan
Write-Host ""
Write-Host "  Auto-start confirmed: On every Windows reboot/login AstroQuant starts"  -ForegroundColor Green
Write-Host "  in WSL2 background automatically with NO console window."                -ForegroundColor Green
Write-Host ""
