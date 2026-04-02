#!/bin/bash
# Configure boot autostart for AstroQuant stack after CPU reboot.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
SERVICE_USER="${AQ_SERVICE_USER:-${SUDO_USER:-$USER}}"
cd "$WORKSPACE"

install_service_template() {
  local template_name="$1"
  sudo sed \
    -e "s|__WORKSPACE__|$WORKSPACE|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    "$WORKSPACE/$template_name" > "/tmp/$template_name"
  sudo mv "/tmp/$template_name" "/etc/systemd/system/$template_name"
}

install_shell_fallback_hook() {
  local bootstrap_script="$WORKSPACE/non_systemd_autostart_bootstrap.sh"
  [ -f "$bootstrap_script" ] && chmod +x "$bootstrap_script" || true

  local hook_start="# >>> astroquant non-systemd autostart >>>"
  local hook_end="# <<< astroquant non-systemd autostart <<<"
  local hook_body='[ -f "'$bootstrap_script'" ] && [ "${AQ_DISABLE_AUTO_START:-0}" != "1" ] && /bin/bash "'$bootstrap_script'" >/dev/null 2>&1 || true'

  install_hook_file() {
    local rc_file="$1"
    [ -f "$rc_file" ] || touch "$rc_file"
    sed -i "/$hook_start/,/$hook_end/d" "$rc_file"
    {
      echo ""
      echo "$hook_start"
      echo "$hook_body"
      echo "$hook_end"
    } >> "$rc_file"
  }

  install_hook_file "$HOME/.bashrc"
  install_hook_file "$HOME/.profile"
  echo "Shell fallback hook installed: $HOME/.bashrc, $HOME/.profile"
}

install_cron_reboot_fallback() {
  local bootstrap_script="$WORKSPACE/non_systemd_autostart_bootstrap.sh"
  [ -f "$bootstrap_script" ] && chmod +x "$bootstrap_script" || true

  if ! command -v crontab >/dev/null 2>&1; then
    echo "Cron fallback skipped: crontab not available"
    return 0
  fi

  local tmp_cron
  tmp_cron=$(mktemp)
  # Remove older AstroQuant reboot entries before adding the canonical one.
  crontab -l 2>/dev/null | grep -v "astroquant reboot bootstrap" | grep -v "npvps_auto_start.sh" > "$tmp_cron" || true
  echo "@reboot cd $WORKSPACE && /bin/bash $bootstrap_script >> $WORKSPACE/data/logs/reboot_autostart.log 2>&1 # astroquant reboot bootstrap" >> "$tmp_cron"
  crontab "$tmp_cron"
  rm -f "$tmp_cron"
  echo "Cron reboot fallback installed: @reboot -> $bootstrap_script"
}

enable_service_link() {
  local service_name="$1"
  sudo mkdir -p /etc/systemd/system/multi-user.target.wants
  sudo ln -sf "/etc/systemd/system/$service_name" "/etc/systemd/system/multi-user.target.wants/$service_name"
}

echo "========================================="
echo "AstroQuant Boot Autostart Setup"
echo "========================================="

# Detect active systemd runtime strictly by PID 1.
if [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
  echo "Detected: systemd active"
  echo "Applying: systemd services autostart"
  sudo bash "$WORKSPACE/setup_best_autostart.sh"
  install_cron_reboot_fallback
  echo ""
  echo "Autostart status (systemd):"
  sudo systemctl is-enabled astroquant_tradingbot.service || true
  sudo systemctl is-enabled cloudflared_tunnel.service || true
  sudo systemctl is-enabled novpn_connector.service || true
  crontab -l 2>/dev/null | grep "astroquant reboot bootstrap" || true
  echo ""
  echo "Result: On CPU reboot, project + remote connectors will auto-start."
  exit 0
fi

# If systemd binaries/files exist but runtime manager isn't active (common in containers),
# still provision boot unit files and enable links for the real host boot sequence.
if [ -d /etc/systemd/system ] && command -v sudo >/dev/null 2>&1; then
  echo "Detected: systemd files available but runtime inactive"
  echo "Applying: offline systemd unit + enable-link provisioning"

  install_service_template astroquant_tradingbot.service
  install_service_template cloudflared_tunnel.service
  install_service_template novpn_connector.service

  enable_service_link astroquant_tradingbot.service
  enable_service_link cloudflared_tunnel.service
  enable_service_link novpn_connector.service

  echo ""
  echo "Autostart status (offline systemd files):"
  ls -l /etc/systemd/system/astroquant_tradingbot.service || true
  ls -l /etc/systemd/system/multi-user.target.wants/astroquant_tradingbot.service || true
  install_cron_reboot_fallback
  install_shell_fallback_hook
  crontab -l 2>/dev/null | grep "astroquant reboot bootstrap" || true
  echo ""
  echo "Result: boot units are pre-enabled; on a real systemd host reboot they auto-start."
  echo "Result: in this non-systemd runtime, AstroQuant auto-starts at terminal/login open."
  exit 0
fi

# Fallback to cron if systemd unavailable.
if command -v crontab >/dev/null 2>&1; then
  echo "Detected: no active systemd"
  echo "Applying: cron @reboot fallback"
  install_cron_reboot_fallback

  echo ""
  echo "Autostart status (cron):"
  crontab -l | grep "astroquant reboot bootstrap" || true
  echo ""
  echo "Result: On CPU reboot, project + remote connectors will auto-start."
  exit 0
fi

echo "Detected: no active systemd and no crontab"
echo "Applying: shell-login bootstrap fallback"
install_shell_fallback_hook

echo ""
echo "Autostart status (shell fallback):"
echo "Bootstrap: $WORKSPACE/non_systemd_autostart_bootstrap.sh"
echo "Hooks installed in: $HOME/.bashrc and $HOME/.profile"
echo ""
echo "Result: AstroQuant will auto-start when terminal/login session opens after reboot."
echo "To disable temporarily: export AQ_DISABLE_AUTO_START=1"
exit 0
