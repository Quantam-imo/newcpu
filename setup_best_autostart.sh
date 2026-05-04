#!/bin/bash
# Best-practice AstroQuant autostart setup: registers all services for full automation
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

install_service_template astroquant_tradingbot.service
install_service_template astroquant_mt5_bridge_sync.service
install_service_template astroquant_mt5_stooq_fallback.service
install_service_template astroquant_mt5_drop_ingest.service
install_service_template astroquant_mt5_drop_ingest.timer
install_service_template astroquant_watchdog.service
install_service_template astroquant_watchdog.timer
install_service_template astroquant_ai_retrain.service
install_service_template astroquant_ai_retrain.timer

sudo systemctl daemon-reload

# Single startup authority: only tradingbot starts the full stack.
sudo systemctl enable astroquant_tradingbot.service
sudo systemctl enable astroquant_mt5_bridge_sync.service
sudo systemctl enable astroquant_mt5_stooq_fallback.service
sudo systemctl enable astroquant_mt5_drop_ingest.timer
sudo systemctl enable astroquant_watchdog.timer
sudo systemctl enable astroquant_ai_retrain.timer

echo "AstroQuant autostart configured with single startup authority."
echo "Enabled services: astroquant_tradingbot.service + astroquant_mt5_bridge_sync.service + astroquant_mt5_stooq_fallback.service + astroquant_mt5_drop_ingest.timer + astroquant_watchdog.timer + astroquant_ai_retrain.timer"
echo ""
echo "NOTE: For dev containers without systemd (docker-init), use ./start_24h.sh instead."
