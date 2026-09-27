#!/usr/bin/env bash
# Guardians of the LANaxy uninstaller
# SPDX-License-Identifier: AGPL-3.0-or-later
set -Eeuo pipefail

readonly PROJECT_DIR="/opt/guardians-of-the-lanaxy"
readonly CONFIG_DIR="/etc/lanaxy"
readonly DATA_DIR="/var/lib/lanaxy"
readonly LOG_DIR="/var/log/lanaxy"
readonly SERVICE_USER="lanlord"
readonly SERVICE_GROUP="lanlord"
readonly LOCK_FILE="/run/lock/lanaxy-bootstrap.lock"

MODE=""
ASSUME_YES=0

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\nWarnung: %s\n' "$*" >&2; }
fail() { printf '\nFehler: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Guardians of the LANaxy – Deinstallation

Aufruf:
  sudo bash uninstall.sh
  sudo bash uninstall.sh --purge --yes
  sudo bash uninstall.sh --keep-data --yes

Optionen:
  --purge       LANaxy inklusive Konfiguration, Datenbank, Backups und Logs entfernen.
  --keep-data   Programm und Systemintegration entfernen, LANaxy-Daten behalten.
  --yes         Rückfrage überspringen. Nur zusammen mit --purge oder --keep-data.
  -h, --help    Diese Hilfe anzeigen.

Installierte Linux-Pakete werden absichtlich nicht automatisch entfernt, da sie
auch von anderen Anwendungen verwendet werden können.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)
            [[ -z "$MODE" || "$MODE" == "purge" ]] || fail "--purge und --keep-data können nicht kombiniert werden."
            MODE="purge"
            ;;
        --keep-data)
            [[ -z "$MODE" || "$MODE" == "keep-data" ]] || fail "--purge und --keep-data können nicht kombiniert werden."
            MODE="keep-data"
            ;;
        --yes)
            ASSUME_YES=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unbekannte Option: $1"
            ;;
    esac
    shift
done

[[ "$(id -u)" -eq 0 ]] || fail "Bitte als root ausführen."

if [[ "$ASSUME_YES" -eq 1 && -z "$MODE" ]]; then
    fail "--yes benötigt zusätzlich --purge oder --keep-data."
fi

if [[ -z "$MODE" ]]; then
    if [[ ! -r /dev/tty ]]; then
        fail "Keine interaktive Konsole verfügbar. Verwende --purge --yes oder --keep-data --yes."
    fi

    say "Guardians of the LANaxy – Deinstallation"
    cat <<'EOF'

Was soll entfernt werden?

  [1] LANaxy vollständig entfernen
      Programm, Konfiguration, Datenbank, Backups und Logs werden gelöscht.

  [2] Programm entfernen, Konfiguration und Daten behalten
      Dienste und Programmdateien werden entfernt. /etc/lanaxy,
      /var/lib/lanaxy und /var/log/lanaxy bleiben für eine spätere
      Neuinstallation erhalten.

  [3] Abbrechen

EOF
    read -r -p "Auswahl [1-3]: " choice </dev/tty
    case "$choice" in
        1) MODE="purge" ;;
        2) MODE="keep-data" ;;
        3) echo "Deinstallation abgebrochen."; exit 0 ;;
        *) fail "Ungültige Auswahl." ;;
    esac
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
    if [[ ! -r /dev/tty ]]; then
        fail "Keine interaktive Konsole verfügbar. Ergänze --yes."
    fi

    echo
    if [[ "$MODE" == "purge" ]]; then
        warn "Alle LANaxy-Konfigurationen, Datenbanken, Backups und Logs werden unwiderruflich gelöscht."
        read -r -p "Wirklich vollständig entfernen? [j/N]: " confirm </dev/tty
    else
        echo "LANaxy wird entfernt, die Datenverzeichnisse bleiben erhalten."
        read -r -p "Fortfahren? [j/N]: " confirm </dev/tty
    fi
    case "$confirm" in
        j|J|ja|JA|Ja|y|Y|yes|YES|Yes) ;;
        *) echo "Deinstallation abgebrochen."; exit 0 ;;
    esac
fi

say "Stoppe und entferne LANaxy-Dienste …"
systemctl disable --now lanaxy-web.service lanaxy.service 2>/dev/null || true

rm -f     /etc/systemd/system/lanaxy.service     /etc/systemd/system/lanaxy-web.service     /usr/bin/lanaxy     /usr/local/bin/lanaxy     /usr/local/sbin/lanaxy-system-helper     /etc/sudoers.d/lanaxy-system-helper     /etc/avahi/services/lanaxy.service

systemctl daemon-reload
systemctl reset-failed lanaxy.service lanaxy-web.service 2>/dev/null || true

say "Entferne Programmdateien und Laufzeitreste …"
rm -rf "$PROJECT_DIR" /run/lanaxy
rm -f     "$LOCK_FILE"     /tmp/lanaxy-health-after-update.json     /var/log/lanaxy.log     /var/log/lanaxy.log.[0-9]*

if [[ "$MODE" == "purge" ]]; then
    say "Entferne LANaxy-Konfiguration, Daten und Logs …"
    rm -rf "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"

    if id "$SERVICE_USER" >/dev/null 2>&1; then
        userdel "$SERVICE_USER" 2>/dev/null || warn "Systembenutzer $SERVICE_USER konnte nicht automatisch entfernt werden."
    fi

    if getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
        groupdel "$SERVICE_GROUP" 2>/dev/null || warn "Systemgruppe $SERVICE_GROUP konnte nicht automatisch entfernt werden."
    fi
else
    say "LANaxy-Daten bleiben erhalten."
    printf '  %s\n  %s\n  %s\n' "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
    echo "Der Systembenutzer lanlord bleibt erhalten, damit die Dateirechte bei einer späteren Neuinstallation konsistent bleiben."
fi

if systemctl is-active --quiet avahi-daemon.service 2>/dev/null; then
    systemctl restart avahi-daemon.service 2>/dev/null || true
fi

say "LANaxy wurde deinstalliert."
if [[ "$MODE" == "keep-data" ]]; then
    echo "Konfiguration und Daten wurden beibehalten."
else
    echo "LANaxy wurde einschließlich seiner eigenen Konfiguration und Daten entfernt."
fi
echo
echo "Von LANaxy installierte Debian/Ubuntu-Pakete wurden nicht automatisch entfernt."
