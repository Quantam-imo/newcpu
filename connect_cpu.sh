#!/bin/bash
# Remote SSH Connection Manager
# Easily connect to your NPVPS CPU from anywhere
# Usage: ./connect_cpu.sh [command]

set -e

# Configuration - EDIT THESE
CPU_USER="${CPU_USER:-cpu}"
CPU_IP="${CPU_IP:-192.168.1.33}"  # Replace with your CPU internal/public IP
CPU_SSH_PORT="${CPU_SSH_PORT:-22}"
CPU_HOSTNAME="${CPU_HOSTNAME:-astroquant-cpu}"

# Derived settings
if [ -n "${SSH_KEY:-}" ]; then
  SSH_KEY="$SSH_KEY"
elif [ -f "${HOME}/.ssh/id_ed25519" ]; then
  SSH_KEY="${HOME}/.ssh/id_ed25519"
else
  SSH_KEY="${HOME}/.ssh/id_rsa"
fi
WORK_DIR="/home/${CPU_USER}/newcpu"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

is_private_ip() {
  case "$1" in
    10.*|192.168.*|172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.3[0-1].*) return 0 ;;
    *) return 1 ;;
  esac
}

in_codespaces() {
  [ "${CODESPACES:-false}" = "true" ] && return 0
  hostname 2>/dev/null | grep -qi 'codespaces' && return 0
  return 1
}

# Show menu if no argument
if [ -z "$1" ]; then
  echo ""
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║  AstroQuant Remote CPU Connection Manager              ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo ""
  echo "Configured CPU:"
  echo "  User:      $CPU_USER"
  echo "  IP:        $CPU_IP"
  echo "  Port:      $CPU_SSH_PORT"
  echo "  Hostname:  $CPU_HOSTNAME"
  echo ""
  echo "Available commands:"
  echo ""
  echo "  ./connect_cpu.sh ssh           - SSH into CPU"
  echo "  ./connect_cpu.sh dashboard     - Port forward dashboard (8000)"
  echo "  ./connect_cpu.sh monitor       - Monitor live status"
  echo "  ./connect_cpu.sh logs          - Follow main log"
  echo "  ./connect_cpu.sh status        - Check system status"
  echo "  ./connect_cpu.sh start         - Start all services"
  echo "  ./connect_cpu.sh stop          - Stop all services"
  echo "  ./connect_cpu.sh restart       - Restart all services"
  echo "  ./connect_cpu.sh tunnel-url    - Get tunnel URL"
  echo "  ./connect_cpu.sh cloudflare    - Show Cloudflare URL"
  echo "  ./connect_cpu.sh novnc         - Show noVNC URL/status"
  echo "  ./connect_cpu.sh novpn         - Alias for novnc"
  echo "  ./connect_cpu.sh remote        - Show both remote endpoints"
  echo "  ./connect_cpu.sh info          - Connection info"
  echo "  ./connect_cpu.sh config        - Show configuration"
  echo ""
  echo "Environment overrides: CPU_IP, CPU_USER, CPU_SSH_PORT, SSH_KEY"
  echo ""
  exit 0
fi

# Test SSH connectivity
test_connection() {
  if [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}✗ SSH private key not found${NC}"
    echo "  Expected key: $SSH_KEY"
    echo "  Try: export SSH_KEY=~/.ssh/id_ed25519"
    echo "  Or create one: ssh-keygen -t ed25519"
    exit 1
  fi

  if ! timeout 5 bash -lc "cat < /dev/null > /dev/tcp/$CPU_IP/$CPU_SSH_PORT" 2>/dev/null; then
    echo -e "${RED}✗ TCP port $CPU_SSH_PORT unreachable at $CPU_IP${NC}"
    if in_codespaces && is_private_ip "$CPU_IP"; then
      echo "  Reason: This shell is in GitHub Codespaces (cloud), but $CPU_IP is a private LAN IP."
      echo "  Private LAN addresses are not reachable from cloud by default."
      echo "  Use Cloudflare URLs for remote UI, or run SSH locally on your Windows/WSL machine."
    fi
    echo "  Check:"
    echo "  1. CPU IP address is correct (current: $CPU_IP)"
    echo "  2. SSH server is running on the CPU"
    echo "  3. Router/firewall allows port $CPU_SSH_PORT if using public IP"
    exit 1
  fi

  if ! timeout 7 ssh \
    -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=no \
    "$CPU_USER@$CPU_IP" "echo 'OK'" > /dev/null 2>&1; then
    echo -e "${RED}✗ SSH handshake/authentication failed${NC}"
    echo "  Target: $CPU_USER@$CPU_IP:$CPU_SSH_PORT"
    echo "  Key:    $SSH_KEY"
    echo "  Check:"
    echo "  1. Correct username ($CPU_USER)"
    echo "  2. Public key installed in ~/.ssh/authorized_keys on CPU"
    echo "  3. SSHD allows key auth (PubkeyAuthentication yes)"
    exit 1
  fi
}

# SSH into CPU
cmd_ssh() {
  echo -e "${BLUE}Connecting to $CPU_USER@$CPU_IP...${NC}"
  ssh -p "$CPU_SSH_PORT" -i "$SSH_KEY" "$CPU_USER@$CPU_IP" -t "cd $WORK_DIR && bash"
}

# Port forward dashboard
cmd_dashboard() {
  echo -e "${GREEN}Dashboard Port Forward${NC}"
  echo "  Remote: $CPU_IP:8000"
  echo "  Local:  127.0.0.1:8000"
  echo ""
  echo "Opening dashboard in 3 seconds..."
  echo "  http://127.0.0.1:8000/frontend/"
  echo ""
  echo "Press Ctrl+C to stop"
  
  sleep 3
  
  # Try to open browser
  if command -v xdg-open > /dev/null 2>&1; then
    xdg-open "http://127.0.0.1:8000/frontend/" 2>/dev/null || true
  elif command -v open > /dev/null 2>&1; then
    open "http://127.0.0.1:8000/frontend/" 2>/dev/null || true
  fi
  
  # Start port forward
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    -L 8000:127.0.0.1:8000 \
    -N \
    "$CPU_USER@$CPU_IP"
}

# Monitor live status
cmd_monitor() {
  echo -e "${BLUE}Connecting to monitor...${NC}"
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && bash monitor_24h_stack.sh"
}

# Follow logs
cmd_logs() {
  echo -e "${BLUE}Following main log...${NC}"
  echo "(Press Ctrl+C to exit)"
  echo ""
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && tail -f data/logs/fullstack.log"
}

# Check status
cmd_status() {
  echo -e "${BLUE}Checking system status...${NC}"
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && curl -s http://127.0.0.1:8000/status | python -m json.tool | head -30"
}

# Start services
cmd_start() {
  echo -e "${BLUE}Starting services on CPU...${NC}"
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && nohup bash npvps_auto_start.sh > data/logs/startup.log 2>&1 &"
  
  sleep 3
  echo -e "${GREEN}✓ Services started in background${NC}"
  echo "Monitor with: ./connect_cpu.sh monitor"
}

# Stop services
cmd_stop() {
  echo -e "${BLUE}Stopping services on CPU...${NC}"
  ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && bash stop_24h_fullstack.sh"
  
  echo -e "${GREEN}✓ Services stopped${NC}"
}

# Restart services
cmd_restart() {
  echo -e "${BLUE}Restarting services on CPU...${NC}"
  cmd_stop
  sleep 3
  cmd_start
  echo -e "${GREEN}✓ Services restarted${NC}"
}

# Get tunnel URL
cmd_tunnel_url() {
  echo -e "${BLUE}Getting tunnel URL...${NC}"
  URL=$(ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && cat data/tunnel_url.txt 2>/dev/null || echo 'Not yet available'")
  
  echo "Tunnel URL: $URL"
  if [[ "$URL" != *"Not yet"* ]]; then
    echo "Dashboard: $URL/frontend/"
  fi
}

# Get Cloudflare URL
cmd_cloudflare() {
  echo -e "${BLUE}Getting Cloudflare URL...${NC}"
  URL=$(ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && cat data/tunnel_url.txt 2>/dev/null || echo 'Not yet available'")

  echo "Cloudflare URL: $URL"
  if [[ "$URL" != *"Not yet"* ]]; then
    echo "Dashboard: $URL/frontend/"
  fi
}

# Get noVNC URL/status
cmd_novnc() {
  echo -e "${BLUE}Getting noVNC status...${NC}"
  LOCAL_URL=$(ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && cat data/novnc_url.txt 2>/dev/null || echo 'noVNC local URL not found'")

  PUBLIC_URL=$(ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && cat data/novnc_tunnel_url.txt 2>/dev/null || echo 'noVNC Cloudflare URL not found'")

  PID=$(ssh -p "$CPU_SSH_PORT" \
    -i "$SSH_KEY" \
    "$CPU_USER@$CPU_IP" \
    "cd $WORK_DIR && cat data/novnc.pid 2>/dev/null || echo ''")

  if [ -n "$PID" ]; then
    RUNNING=$(ssh -p "$CPU_SSH_PORT" \
      -i "$SSH_KEY" \
      "$CPU_USER@$CPU_IP" \
      "kill -0 $PID 2>/dev/null && echo RUNNING || echo STOPPED")
  else
    RUNNING="UNKNOWN"
  fi

  echo "noVNC Status: $RUNNING"
  echo "noVNC Local URL: $LOCAL_URL"
  echo "noVNC Cloudflare URL: $PUBLIC_URL"
}

# Backward compatible alias
cmd_novpn() {
  cmd_novnc
}

# Show both endpoints
cmd_remote() {
  echo -e "${BLUE}Getting all remote endpoints...${NC}"
  cmd_cloudflare
  echo ""
  cmd_novnc
}

# Connection info
cmd_info() {
  echo ""
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║  Connection Information                                ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo ""
  echo "SSH Connection:"
  echo "  Command: ssh -i $SSH_KEY $CPU_USER@$CPU_IP"
  echo ""
  echo "Port Forwarding (Dashboard):"
  echo "  ssh -i $SSH_KEY -L 8000:127.0.0.1:8000 $CPU_USER@$CPU_IP"
  echo ""
  echo "Direct Access (if on same network):"
  echo "  ssh $CPU_USER@$CPU_HOSTNAME (if mDNS configured)"
  echo ""
  echo "Quick Commands:"
  echo "  ./connect_cpu.sh dashboard - Start dashboard port forward"
  echo "  ./connect_cpu.sh monitor   - Live monitoring"
  echo "  ./connect_cpu.sh logs      - Follow logs"
  echo "  ./connect_cpu.sh remote    - Show Cloudflare + noVNC endpoints"
  echo ""
}

# Show config
cmd_config() {
  echo ""
  echo "╔════════════════════════════════════════════════════════╗"
  echo "║  Current Configuration                                 ║"
  echo "╚════════════════════════════════════════════════════════╝"
  echo ""
  echo "Edit this script to change:"
  echo ""
  echo "  CPU_USER=\"$CPU_USER\""
  echo "  CPU_IP=\"$CPU_IP\""
  echo "  CPU_SSH_PORT=\"$CPU_SSH_PORT\""
  echo "  CPU_HOSTNAME=\"$CPU_HOSTNAME\""
  echo "  SSH_KEY=\"$SSH_KEY\""
  echo ""
  echo "Or use environment variables:"
  echo "  export CPU_IP=192.168.1.33"
  echo "  export CPU_USER=astroquant"
  echo "  export SSH_KEY=~/.ssh/id_ed25519"
  echo "  ./connect_cpu.sh ssh"
  echo ""
}

# Route to command
case "$1" in
  ssh)
    test_connection
    cmd_ssh
    ;;
  dashboard)
    test_connection
    cmd_dashboard
    ;;
  monitor)
    test_connection
    cmd_monitor
    ;;
  logs)
    test_connection
    cmd_logs
    ;;
  status)
    test_connection
    cmd_status
    ;;
  start)
    test_connection
    cmd_start
    ;;
  stop)
    test_connection
    cmd_stop
    ;;
  restart)
    test_connection
    cmd_restart
    ;;
  tunnel-url)
    test_connection
    cmd_tunnel_url
    ;;
  cloudflare)
    test_connection
    cmd_cloudflare
    ;;
  novnc)
    test_connection
    cmd_novnc
    ;;
  novpn)
    test_connection
    cmd_novpn
    ;;
  remote)
    test_connection
    cmd_remote
    ;;
  info)
    cmd_info
    ;;
  config)
    cmd_config
    ;;
  *)
    echo "Unknown command: $1"
    echo "Run without arguments for help"
    exit 1
    ;;
esac
