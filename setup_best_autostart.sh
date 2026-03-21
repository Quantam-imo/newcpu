#!/bin/bash
# Best-practice AstroQuant autostart setup: registers all services for full automation
set -e

cd /workspaces/newcpu

sudo cp astroquant_tradingbot.service /etc/systemd/system/
sudo cp chrome_remote_debug.service /etc/systemd/system/
sudo cp cloudflared_tunnel.service /etc/systemd/system/
sudo cp astroquant_orchestrator.service /etc/systemd/system/
sudo cp astroquant_celery.service /etc/systemd/system/
sudo cp astroquant_calibrate.service /etc/systemd/system/
sudo cp astroquant_healthcheck.service /etc/systemd/system/
sudo cp astroquant_livesync.service /etc/systemd/system/

sudo systemctl daemon-reload

sudo systemctl enable astroquant_tradingbot.service
sudo systemctl enable chrome_remote_debug.service
sudo systemctl enable cloudflared_tunnel.service
sudo systemctl enable astroquant_orchestrator.service
sudo systemctl enable astroquant_celery.service
sudo systemctl enable astroquant_calibrate.service
sudo systemctl enable astroquant_healthcheck.service
sudo systemctl enable astroquant_livesync.service

echo "All AstroQuant services registered and enabled for autostart."
echo "On next CPU boot, the full stack will launch automatically."
