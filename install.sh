#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/guardians-of-the-lanaxy"
CONFIG_DIR="/etc/lanaxy"

if [ "$(id -u)" -ne 0 ]; then
    echo "Fehler: Die Installation muss als root ausgeführt werden." >&2
    exit 1
fi

cd "$PROJECT_DIR"

apt update
apt install -y \
    python3-yaml \
    python3-paho-mqtt \
    python3-requests \
    python3-flask \
    python3-gunicorn \
    sudo \
    avahi-daemon \
    iputils-ping \
    netcat-openbsd

mkdir -p \
    "$CONFIG_DIR" \
    /var/lib/lanaxy \
    /var/log/lanaxy \
    "$CONFIG_DIR/backups" \
    "$CONFIG_DIR/guardians.d" \
    "$CONFIG_DIR/beacons.d" \
    "$CONFIG_DIR/portals.d"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    if [ ! -f examples/config.yaml ]; then
        echo "Fehler: Die neutrale Konfigurationsvorlage examples/config.yaml fehlt." >&2
        exit 1
    fi
    install -m 0640 examples/config.yaml "$CONFIG_DIR/config.yaml"
fi

chmod +x \
    lanaxy.py \
    bin/lanaxy \
    web/run.py \
    install.sh \
    update.sh \
    scripts/setup-lanlord.sh \
    scripts/lanaxy-system-helper \
    scripts/deploy-public-installer.sh

systemctl stop lanaxy.service lanaxy-web.service 2>/dev/null || true

./scripts/setup-lanlord.sh

ln -sf "$PROJECT_DIR/bin/lanaxy" /usr/bin/lanaxy
ln -sf "$PROJECT_DIR/bin/lanaxy" /usr/local/bin/lanaxy

install -o root -g root -m 0644 \
    systemd/lanaxy.service \
    /etc/systemd/system/lanaxy.service
install -o root -g root -m 0644 \
    systemd/lanaxy-web.service \
    /etc/systemd/system/lanaxy-web.service

systemctl daemon-reload
systemctl enable --now lanaxy.service lanaxy-web.service

sleep 3
runuser -u lanlord -- /usr/bin/lanaxy doctor

IP_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$IP_ADDRESS" ] || IP_ADDRESS="SERVER-IP"

echo
echo "LANaxy wurde erfolgreich installiert."
echo
echo "Weboberfläche: http://${IP_ADDRESS}:8090"
echo "CLI:            $(command -v lanaxy || echo /usr/bin/lanaxy)"
echo "Statusprüfung:  lanaxy doctor"
echo
