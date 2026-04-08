#!/bin/bash
# Best-practice AstroQuant autostart setup: registers all services for full automation
# Physical CPU (32GB RAM / 1TB SSD) — single startup authority via astroquant_tradingbot
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
SERVICE_USER="${AQ_SERVICE_USER:-${SUDO_USER:-$USER}}"

install_service_template() {
	local template_name="$1"
	sudo sed \
		-e "s|__WORKSPACE__|$WORKSPACE|g" \
		-e "s|__SERVICE_USER__|$SERVICE_USER|g" \
		"$WORKSPACE/$template_name" > "/tmp/$template_name"
	sudo mv "/tmp/$template_name" "/etc/systemd/system/$template_name"
}

cd "$WORKSPACE"
chmod +x "$WORKSPACE/watchdog_autorecover.sh" 2>/dev/null || true

# Core services
install_service_template astroquant_tradingbot.service
install_service_template astroquant_watchdog.service
install_service_template astroquant_watchdog.timer

# Individual component services (standalone — tradingbot also manages these internally)
for svc in astroquant_livesync.service astroquant_celery.service chrome_remote_debug.service; do
	[ -f "$WORKSPACE/$svc" ] && install_service_template "$svc" || true
done

sudo systemctl daemon-reload

# Single startup authority: astroquant_tradingbot starts the full stack automatically.
# Individual services (livesync/celery/chrome) are watchdog-managed inside fullstack loop.
sudo systemctl enable astroquant_tradingbot.service
sudo systemctl enable astroquant_watchdog.timer

# Enable individual recovery services (no autostart — only tradingbot starts them)
for svc in astroquant_livesync.service astroquant_celery.service chrome_remote_debug.service; do
	sudo systemctl enable "$svc" 2>/dev/null || true
done

echo ""
echo "✓ AstroQuant autostart configured (physical CPU mode)"
echo "  Startup chain: systemd → astroquant_tradingbot → fullstack script → all services"
echo "  Watchdog:      astroquant_watchdog.timer (every 60s)"
echo ""
echo "Enabled services:"
sudo systemctl is-enabled astroquant_tradingbot.service 2>/dev/null || true
sudo systemctl is-enabled astroquant_watchdog.timer 2>/dev/null || true
echo ""
echo "NOTE: For dev containers without systemd (docker-init), use ./start_24h_fullstack.sh"
