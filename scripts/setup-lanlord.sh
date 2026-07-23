#!/bin/bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/guardians-of-the-lanaxy}"
CONFIG_DIR="${CONFIG_DIR:-/etc/lanaxy}"
DATA_DIR="${DATA_DIR:-/var/lib/lanaxy}"
LOG_DIR="${LOG_DIR:-/var/log/lanaxy}"
SERVICE_USER="lanlord"
SERVICE_GROUP="lanlord"

if [ "$(id -u)" -ne 0 ]; then
    echo "Fehler: Die LANLord-Einrichtung muss als root ausgeführt werden." >&2
    exit 1
fi

if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    groupadd --system "$SERVICE_GROUP"
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd \
        --system \
        --gid "$SERVICE_GROUP" \
        --home-dir "$DATA_DIR" \
        --create-home \
        --shell /usr/sbin/nologin \
        --comment "LANLord – LANaxy service account" \
        "$SERVICE_USER"
else
    usermod \
        --home "$DATA_DIR" \
        --shell /usr/sbin/nologin \
        --comment "LANLord – LANaxy service account" \
        "$SERVICE_USER"
fi

# Diagnostic bundles include the journals of both LANaxy services. Membership
# in systemd-journal grants read-only access to the system journal without
# running the web service as root or granting broad sudo permissions.
if getent group systemd-journal >/dev/null 2>&1; then
    usermod -a -G systemd-journal "$SERVICE_USER"
fi

mkdir -p \
    "$CONFIG_DIR" \
    "$CONFIG_DIR/backups" \
    "$CONFIG_DIR/guardians.d" \
    "$CONFIG_DIR/beacons.d" \
    "$CONFIG_DIR/portals.d" \
    "$DATA_DIR" \
    "$LOG_DIR"

# Older LANaxy versions stored the rotating log directly in /var/log.
# That location is intentionally not writable by LANLord. Migrate both the
# configuration and any existing file into the dedicated LANaxy directory.
if [ -f "$CONFIG_DIR/config.yaml" ]; then
    PROJECT_DIR="$PROJECT_DIR" \
    CONFIG_DIR="$CONFIG_DIR" \
    LOG_DIR="$LOG_DIR" \
    python3 - <<'PY'
import os
import shutil
from pathlib import Path

import yaml

config_path = Path(os.environ["CONFIG_DIR"]) / "config.yaml"
log_dir = Path(os.environ["LOG_DIR"])
config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
lanaxy = config.setdefault("lanaxy", {})

old_value = str(lanaxy.get("log_file", "") or "")
new_path = log_dir / "lanaxy.log"

needs_migration = (
    not old_value
    or old_value == "/var/log/lanaxy.log"
    or not Path(old_value).is_relative_to(log_dir)
)

if needs_migration:
    old_path = Path(old_value) if old_value else None
    log_dir.mkdir(parents=True, exist_ok=True)

    if (
        old_path
        and old_path.is_file()
        and old_path.resolve() != new_path.resolve()
        and not new_path.exists()
    ):
        shutil.move(str(old_path), str(new_path))

    lanaxy["log_file"] = str(new_path)
    temporary = config_path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(
            config,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(config_path)
    print(f"Logpfad migriert: {new_path}")
PY
fi

# Application code remains controlled by root and is only readable/executable
# by LANLord. Custom plugins and writable state live outside the code tree.
chown -R root:"$SERVICE_GROUP" "$PROJECT_DIR"
find "$PROJECT_DIR" -type d -exec chmod 0750 {} +
find "$PROJECT_DIR" -type f -exec chmod 0640 {} +
chmod 0750 \
    "$PROJECT_DIR/lanaxy.py" \
    "$PROJECT_DIR/bin/lanaxy" \
    "$PROJECT_DIR/web/run.py" \
    "$PROJECT_DIR/install.sh" \
    "$PROJECT_DIR/update.sh" \
    "$PROJECT_DIR/scripts/setup-lanlord.sh"

# LANaxy's web UI must be able to atomically replace config files and manage
# custom plugins/backups, so these dedicated directories belong to LANLord.
chown "$SERVICE_USER":"$SERVICE_GROUP" "$CONFIG_DIR"
chmod 0750 "$CONFIG_DIR"

for directory in \
    "$CONFIG_DIR/backups" \
    "$CONFIG_DIR/guardians.d" \
    "$CONFIG_DIR/beacons.d" \
    "$CONFIG_DIR/portals.d"
do
    chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$directory"
    find "$directory" -type d -exec chmod 0750 {} +
    find "$directory" -type f -exec chmod 0640 {} +
done

if [ -f "$CONFIG_DIR/config.yaml" ]; then
    chown "$SERVICE_USER":"$SERVICE_GROUP" "$CONFIG_DIR/config.yaml"
    chmod 0600 "$CONFIG_DIR/config.yaml"
fi

if [ -f "$CONFIG_DIR/web-secret" ]; then
    chown "$SERVICE_USER":"$SERVICE_GROUP" "$CONFIG_DIR/web-secret"
    chmod 0600 "$CONFIG_DIR/web-secret"
fi

chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$DATA_DIR" "$LOG_DIR"
find "$DATA_DIR" "$LOG_DIR" -type d -exec chmod 0750 {} +
find "$DATA_DIR" "$LOG_DIR" -type f -exec chmod 0600 {} +

# Move legacy rotations too, if they still exist after an interrupted update.
for legacy_log in /var/log/lanaxy.log /var/log/lanaxy.log.[0-9]*; do
    [ -e "$legacy_log" ] || continue
    target="$LOG_DIR/$(basename "$legacy_log" | sed 's/^lanaxy\.log/lanaxy.log/')"
    if [ ! -e "$target" ]; then
        mv "$legacy_log" "$target"
    else
        rm -f "$legacy_log"
    fi
done

chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$LOG_DIR"
find "$LOG_DIR" -type d -exec chmod 0750 {} +
find "$LOG_DIR" -type f -exec chmod 0600 {} +


# Narrowly scoped privileged helper for host timezone and mDNS control.
install -o root -g root -m 0755 \
    "$PROJECT_DIR/scripts/lanaxy-system-helper" \
    /usr/local/sbin/lanaxy-system-helper
cat > /etc/sudoers.d/lanaxy-system-helper <<'SUDOERS'
lanlord ALL=(root) NOPASSWD: /usr/local/sbin/lanaxy-system-helper
SUDOERS
chmod 0440 /etc/sudoers.d/lanaxy-system-helper
visudo -cf /etc/sudoers.d/lanaxy-system-helper >/dev/null

mkdir -p /etc/avahi/services
cat > /etc/avahi/services/lanaxy.service <<'AVAHI'
<?xml version="1.0" standalone='no'?><!--*-nxml-*-->
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">LANaxy on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>8090</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
AVAHI

echo "LANLord eingerichtet: ${SERVICE_USER}:${SERVICE_GROUP}"
