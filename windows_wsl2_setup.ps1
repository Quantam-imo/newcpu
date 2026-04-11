# AstroQuant - Windows WSL2 Full Setup Script
# Run this on your Windows PC as Administrator
# PowerShell: Right-click PowerShell -> "Run as Administrator"
# Then paste:
#   Set-ExecutionPolicy Bypass -Scope Process -Force; .\windows_wsl2_setup.ps1

param(
    [string]$GithubRepo = "https://github.com/Quantam-imo/newcpu.git",
    [string]$WslUser    = "astroquant",
    [string]$InstallDir = "/home/astroquant/newcpu"
)

$ErrorActionPreference = "Stop"

function Write-Header([string]$msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}
function Write-OK([string]$msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-WARN([string]$msg) { Write-Host "  [!!]  $msg" -ForegroundColor Yellow }
function Write-STEP([string]$msg) { Write-Host "  -->   $msg" -ForegroundColor White }

# --- 0. Must run as Admin ---
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Please run PowerShell as Administrator." -ForegroundColor Red
    Write-Host "  Right-click PowerShell -> Run as Administrator" -ForegroundColor Yellow
    pause; exit 1
}

# --- 0b. OS and architecture check ---
Write-Header "Pre-flight: System Compatibility Check"

if (-NOT [System.Environment]::Is64BitOperatingSystem) {
    Write-Host "ERROR: This machine is NOT 64-bit. AstroQuant requires a 64-bit Windows OS." -ForegroundColor Red
    pause; exit 1
}
Write-OK "64-bit OS confirmed"

$cpuArch = (Get-WmiObject Win32_Processor).Architecture
if ($cpuArch -eq 12) {
    Write-WARN "ARM64 processor detected. Chrome amd64 may not run natively."
} elseif ($cpuArch -ne 9) {
    Write-Host "ERROR: Unsupported CPU architecture ($cpuArch). Requires x64 (Intel/AMD)." -ForegroundColor Red
    pause; exit 1
}
Write-OK "x64 processor confirmed"

$osBuild    = [System.Environment]::OSVersion.Version.Build
$winEdition = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").ProductName
Write-OK "OS: $winEdition (Build $osBuild)"

if ($osBuild -lt 19041) {
    Write-Host "ERROR: WSL2 requires Windows 10 Build 19041 or later." -ForegroundColor Red
    pause; exit 1
}
Write-OK "Windows version supported"

Write-Header "AstroQuant WSL2 Installer"
Write-Host "  This script will:"
Write-Host "    1. Enable WSL2"
Write-Host "    2. Install Ubuntu 22.04"
Write-Host "    3. Clone AstroQuant from GitHub"
Write-Host "    4. Install Python environment + all packages"
Write-Host "    5. Configure autostart on every Windows reboot"
Write-Host ""

# --- 1. Enable WSL2 features ---
Write-Header "Step 1/5 - Enabling WSL2"

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
$vmFeature  = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform

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

# --- 2. Set WSL2 as default ---
Write-Header "Step 2/5 - Setting WSL2 as default"

$wslKernelUrl  = "https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi"
$wslKernelPath = "$env:TEMP\wsl_update_x64.msi"

$wslStatus = & wsl --status 2>&1
if ("$wslStatus" -notmatch "2") {
    Write-STEP "Downloading WSL2 kernel update..."
    try {
        Invoke-WebRequest -Uri $wslKernelUrl -OutFile $wslKernelPath -UseBasicParsing
        Start-Process msiexec.exe -ArgumentList "/i `"$wslKernelPath`" /quiet /norestart" -Wait
        Write-OK "WSL2 kernel installed"
    } catch {
        Write-WARN "Could not auto-download kernel. Visit: https://aka.ms/wsl2kernel"
    }
}

& wsl --set-default-version 2 2>&1 | Out-Null
Write-OK "Default WSL version set to 2"

# --- 3. Install Ubuntu 22.04 ---
Write-Header "Step 3/5 - Installing Ubuntu 22.04"

$distroList = & wsl --list --quiet 2>&1
if ("$distroList" -match "Ubuntu-22.04") {
    Write-OK "Ubuntu-22.04 already installed - skipping"
} else {
    Write-STEP "Installing Ubuntu 22.04 (this may take 3-5 min)..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Canonical.Ubuntu.2204 --accept-package-agreements --accept-source-agreements --silent
    } else {
        & wsl --install -d Ubuntu-22.04 --no-launch
    }
    Write-OK "Ubuntu-22.04 installed"
    Write-WARN "Ubuntu needs first-time setup. A window will open."
    Write-WARN "IMPORTANT: Use Linux username: $WslUser"
    Write-Host ""
    Write-Host "  Press ENTER to launch Ubuntu first-time setup..." -ForegroundColor Yellow
    Read-Host
    & wsl -d Ubuntu-22.04
}

# --- 4. Setup AstroQuant inside WSL2 ---
Write-Header "Step 4/5 - Setting up AstroQuant inside WSL2"

$nl = "`n"

$ls  = '#!/bin/bash' + $nl
$ls += 'set -e' + $nl
$ls += 'echo "==================================================="' + $nl
$ls += 'echo "  AstroQuant WSL2 Linux Setup"' + $nl
$ls += 'echo "==================================================="' + $nl
$ls += 'echo "[1/6] Installing system packages..."' + $nl
$ls += 'sudo apt-get update -qq 2>/dev/null' + $nl
$ls += 'sudo apt-get install -y -qq python3 python3-pip python3-venv redis-server git curl wget unzip build-essential libssl-dev libffi-dev 2>/dev/null' + $nl
$ls += 'echo "  [OK] System packages installed"' + $nl
$ls += 'echo "[2/6] Installing Google Chrome..."' + $nl
$ls += 'if ! command -v google-chrome &>/dev/null && ! command -v google-chrome-stable &>/dev/null; then' + $nl
$ls += '    curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb 2>/dev/null' + $nl
$ls += '    sudo dpkg -i /tmp/chrome.deb 2>/dev/null || sudo apt-get install -f -y -qq 2>/dev/null' + $nl
$ls += '    rm -f /tmp/chrome.deb' + $nl
$ls += '    echo "  [OK] Google Chrome installed"' + $nl
$ls += 'else' + $nl
$ls += '    echo "  [OK] Google Chrome already present"' + $nl
$ls += 'fi' + $nl
$ls += 'echo "[3/6] Cloning AstroQuant project..."' + $nl
$ls += 'INSTALL_DIR="' + $InstallDir + '"' + $nl
$ls += 'if [ -d "$INSTALL_DIR/.git" ]; then' + $nl
$ls += '    echo "  Already cloned - pulling latest..."' + $nl
$ls += '    cd "$INSTALL_DIR" && git pull' + $nl
$ls += 'else' + $nl
$ls += '    git clone ' + $GithubRepo + ' "$INSTALL_DIR"' + $nl
$ls += 'fi' + $nl
$ls += 'cd "$INSTALL_DIR"' + $nl
$ls += 'mkdir -p data/logs' + $nl
$ls += 'echo "  [OK] Project ready"' + $nl
$ls += 'echo "[4/6] Setting up Python virtual environment..."' + $nl
$ls += 'python3 -m venv .venv' + $nl
$ls += 'source .venv/bin/activate' + $nl
$ls += 'pip install --upgrade pip -q' + $nl
$ls += 'echo "  Installing Python packages (3-5 min)..."' + $nl
$ls += 'pip install -r requirements.txt -q' + $nl
$ls += 'python -m playwright install chromium 2>/dev/null || true' + $nl
$ls += 'echo "  [OK] Python environment ready"' + $nl
$ls += 'echo "[5/6] Configuring WSL2 systemd boot..."' + $nl
$ls += 'printf "[boot]\nsystemd=true\ncommand=/bin/bash ' + $InstallDir + '/non_systemd_autostart_bootstrap.sh\n\n[automount]\nenabled = true\n" | sudo tee /etc/wsl.conf > /dev/null' + $nl
$ls += 'echo "  [OK] /etc/wsl.conf configured"' + $nl
$ls += 'chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true' + $nl
$ls += 'echo "[6/6] Registering autostart hooks..."' + $nl
$ls += 'AQ_WORKSPACE="$INSTALL_DIR" bash "$INSTALL_DIR/enable_boot_autostart.sh" || true' + $nl
$ls += 'echo "  [OK] Autostart registered"' + $nl
$ls += 'echo "==================================================="' + $nl
$ls += 'echo "  WSL2 Linux Setup COMPLETE"' + $nl
$ls += 'echo "==================================================="' + $nl

Write-STEP "Writing setup script to WSL2..."
$ls | & wsl -d Ubuntu-22.04 -- bash -c "cat > /tmp/aq_linux_setup.sh && chmod +x /tmp/aq_linux_setup.sh"

$envSourcePath = "$env:USERPROFILE\Desktop\astroquant_env.txt"
$envExists = Test-Path $envSourcePath
if ($envExists) {
    Write-STEP "Copying .env from Desktop into WSL2..."
    $envContent = Get-Content $envSourcePath -Raw
    $envContent | & wsl -d Ubuntu-22.04 -- bash -c "mkdir -p $InstallDir && cat > $InstallDir/.env"
    Write-OK ".env injected from Desktop\astroquant_env.txt"
} else {
    Write-WARN "astroquant_env.txt not found on Desktop - .env will be copied later"
}

Write-STEP "Running Linux setup inside WSL2 (5-10 min)..."
& wsl -d Ubuntu-22.04 -- bash /tmp/aq_linux_setup.sh
Write-OK "Linux environment configured"

# --- 5. Windows autostart ---
Write-Header "Step 5/5 - Configuring Windows autostart"

$vbsLines  = 'Set oShell = CreateObject("WScript.Shell")' + "`r`n"
$vbsLines += 'oShell.Run "wsl -d Ubuntu-22.04 -- bash -c ""cd ' + $InstallDir + ' && bash non_systemd_autostart_bootstrap.sh >> data/logs/windows_autostart.log 2>&1""", 0, False' + "`r`n"

$startupFolder = [System.IO.Path]::Combine($env:APPDATA, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
$vbsPath = [System.IO.Path]::Combine($startupFolder, "AstroQuant_Autostart.vbs")

if (-not (Test-Path $startupFolder)) {
    New-Item -ItemType Directory -Path $startupFolder -Force | Out-Null
}
Set-Content -Path $vbsPath -Value $vbsLines -Encoding ASCII
Write-OK "Startup VBScript created"

$taskName     = "AstroQuant_WSL2_Autostart"
$taskAction   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""
$taskTrigger1 = New-ScheduledTaskTrigger -AtLogOn
$taskTrigger2 = New-ScheduledTaskTrigger -AtStartup
$taskSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $taskAction `
    -Trigger $taskTrigger1, $taskTrigger2 `
    -Settings $taskSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-OK "Task Scheduler entry registered: $taskName"

# --- Done ---
Write-Header "SETUP COMPLETE"
Write-Host ""
Write-Host "  AstroQuant is configured for 24/7 auto-start on this Windows PC!" -ForegroundColor Green
Write-Host ""
Write-Host "  NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Restart WSL2 to activate systemd:" -ForegroundColor White
Write-Host "       wsl --shutdown" -ForegroundColor Cyan
Write-Host "       Then restart Windows" -ForegroundColor White
Write-Host ""
if (-not $envExists) {
    Write-Host "  2. IMPORTANT - Copy your .env into WSL2:" -ForegroundColor Red
    Write-Host "     Save .env to your Desktop as: astroquant_env.txt" -ForegroundColor Yellow
    Write-Host "     Then in WSL2 Ubuntu terminal run:" -ForegroundColor Yellow
    Write-Host "       cp /mnt/c/Users/$env:USERNAME/Desktop/astroquant_env.txt $InstallDir/.env" -ForegroundColor Cyan
    Write-Host ""
}
Write-Host "  3. After restart verify (in WSL2 Ubuntu terminal):" -ForegroundColor White
Write-Host "       curl http://localhost:8000/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "  On every Windows reboot, AstroQuant starts automatically in WSL2." -ForegroundColor Green
Write-Host ""
