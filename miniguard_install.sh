#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "MiniGuard muss als root installiert werden." >&2; exit 1; }
LANAXY=""; AGENT_ID=""; CODE=""; INSECURE=0; UPDATE=0
while [ $# -gt 0 ]; do
 case "$1" in
  --lanaxy) LANAXY=$2; shift 2;;
  --agent-id) AGENT_ID=$2; shift 2;;
  --code) CODE=$2; shift 2;;
  --insecure) INSECURE=1; shift;;
  --update) UPDATE=1; shift;;
  *) echo "Unbekannter Parameter: $1" >&2; exit 2;;
 esac
done
[ -n "$LANAXY" ] && [ -n "$AGENT_ID" ] || { echo "Parameter fehlen." >&2; exit 2; }
if [ "$UPDATE" -eq 0 ]; then [ -n "$CODE" ] || { echo "Registrierungscode fehlt." >&2; exit 2; }; fi
command -v python3 >/dev/null || { echo "python3 fehlt." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl fehlt." >&2; exit 1; }
curl -fsSL "$LANAXY/miniguard/agent.py" -o /usr/local/bin/miniguard
chmod 0755 /usr/local/bin/miniguard
EXTRA=""; [ "$INSECURE" -eq 0 ] || EXTRA="--insecure"
if [ "$UPDATE" -eq 0 ]; then
  /usr/local/bin/miniguard register --lanaxy "$LANAXY" --agent-id "$AGENT_ID" --code "$CODE" $EXTRA
else
  [ -f /etc/miniguard/config.json ] || { echo "Keine vorhandene MiniGuard-Registrierung gefunden." >&2; exit 1; }
fi
cat >/etc/systemd/system/miniguard.service <<'EOF'
[Unit]
Description=LANaxy MiniGuard Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/miniguard daemon
Restart=always
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/miniguard /usr/local/bin

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable miniguard.service >/dev/null 2>&1 || true
systemctl restart miniguard.service
echo "MiniGuard installiert beziehungsweise aktualisiert und gestartet."
