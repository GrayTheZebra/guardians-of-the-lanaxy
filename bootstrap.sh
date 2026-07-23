#!/usr/bin/env bash
# Guardians of the LANaxy public bootstrap installer
# SPDX-License-Identifier: AGPL-3.0-or-later
set -Eeuo pipefail

readonly REPOSITORY="GrayTheZebra/guardians-of-the-lanaxy"
readonly PROJECT_DIR="/opt/guardians-of-the-lanaxy"
readonly CONFIG_DIR="/etc/lanaxy"
readonly CODE_BACKUP_DIR="${CONFIG_DIR}/code-backups"
readonly RELEASE_BASE="https://github.com/${REPOSITORY}/releases/latest/download"
readonly RELEASE_ZIP_URL="${RELEASE_BASE}/guardians-of-the-lanaxy.zip"
readonly RELEASE_SHA_URL="${RELEASE_BASE}/guardians-of-the-lanaxy.zip.sha256"
readonly LOCK_FILE="/run/lock/lanaxy-bootstrap.lock"

WORK_DIR=""
RESTORE_ARCHIVE=""
DEPLOY_STARTED=0

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\nWarnung: %s\n' "$*" >&2; }
fail() { printf '\nFehler: %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}

restore_previous_code() {
    [[ "$DEPLOY_STARTED" -eq 1 ]] || return 0
    [[ -n "$RESTORE_ARCHIVE" && -f "$RESTORE_ARCHIVE" ]] || return 0

    warn "Die neue Version konnte nicht eingerichtet werden. Stelle den vorherigen Programmstand wieder her."
    systemctl stop lanaxy-web.service lanaxy.service 2>/dev/null || true
    mkdir -p "$PROJECT_DIR"
    find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
    tar -xzf "$RESTORE_ARCHIVE" -C "$PROJECT_DIR"
    if [[ -x "$PROJECT_DIR/scripts/setup-lanlord.sh" ]]; then
        "$PROJECT_DIR/scripts/setup-lanlord.sh" || true
    fi
    systemctl daemon-reload 2>/dev/null || true
    systemctl restart lanaxy.service lanaxy-web.service 2>/dev/null || true
}

on_error() {
    local exit_code=$?
    trap - ERR
    local line=${1:-unknown}
    restore_previous_code
    printf '\nFehler: Die Installation wurde in Zeile %s abgebrochen.\n' "$line" >&2
    exit "$exit_code"
}

trap cleanup EXIT
trap 'on_error "$LINENO"' ERR

[[ "$(id -u)" -eq 0 ]] || fail "Bitte als root ausführen, zum Beispiel: curl -fsSL https://lanaxy.de/install.sh | sudo bash"
[[ -r /etc/os-release ]] || fail "Linux-Distribution konnte nicht erkannt werden."

# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
    debian|ubuntu) ;;
    *) fail "${PRETTY_NAME:-Diese Distribution} wird vom Ein-Befehl-Installer derzeit nicht unterstützt." ;;
esac

command -v systemctl >/dev/null 2>&1 || fail "LANaxy benötigt ein systemd-basiertes System."
mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "Eine andere LANaxy-Installation oder ein Update läuft bereits."

say "Guardians of the LANaxy – Installation"
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates curl unzip rsync python3 >/dev/null

WORK_DIR="$(mktemp -d /tmp/lanaxy-install.XXXXXXXX)"
readonly ARCHIVE="$WORK_DIR/guardians-of-the-lanaxy.zip"
readonly CHECKSUM="$WORK_DIR/guardians-of-the-lanaxy.zip.sha256"
readonly UNPACKED="$WORK_DIR/unpacked"

say "Lade die aktuelle stabile Version von GitHub …"
curl --fail --silent --show-error --location --retry 3 --retry-all-errors \
    --connect-timeout 15 --proto '=https' --tlsv1.2 \
    --output "$ARCHIVE" "$RELEASE_ZIP_URL"
curl --fail --silent --show-error --location --retry 3 --retry-all-errors \
    --connect-timeout 15 --proto '=https' --tlsv1.2 \
    --output "$CHECKSUM" "$RELEASE_SHA_URL"

EXPECTED="$(awk 'NF {print $1; exit}' "$CHECKSUM")"
ACTUAL="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$EXPECTED" =~ ^[a-fA-F0-9]{64}$ ]] || fail "Die veröffentlichte SHA-256-Prüfsumme ist ungültig."
[[ "$EXPECTED" == "$ACTUAL" ]] || fail "Die SHA-256-Prüfsumme des Downloads stimmt nicht."

# Reject absolute paths and parent traversal before extraction.
while IFS= read -r entry; do
    [[ "$entry" != /* ]] || fail "Das Release-Archiv enthält einen absoluten Pfad."
    [[ "/$entry/" != *"/../"* ]] || fail "Das Release-Archiv enthält einen unsicheren Pfad."
done < <(unzip -Z1 "$ARCHIVE")

say "Prüfsumme bestätigt. Entpacke LANaxy …"
mkdir -p "$UNPACKED"
unzip -q "$ARCHIVE" -d "$UNPACKED"
readonly SOURCE_DIR="$UNPACKED/guardians-of-the-lanaxy"

required_files=(
    lanaxy.py install.sh update.sh bootstrap.sh
    examples/config.yaml systemd/lanaxy.service systemd/lanaxy-web.service
    LICENSE THIRD_PARTY_LICENSES.md
)
for required_file in "${required_files[@]}"; do
    [[ -f "$SOURCE_DIR/$required_file" ]] || fail "Das Release ist unvollständig: $required_file fehlt."
done

IS_UPDATE=0
if [[ -f "$CONFIG_DIR/config.yaml" && -d "$PROJECT_DIR" && -f "$PROJECT_DIR/update.sh" ]]; then
    IS_UPDATE=1
fi

if [[ "$IS_UPDATE" -eq 1 ]]; then
    say "Vorhandene Installation erkannt. Sichere den aktuellen Programmstand …"
    mkdir -p "$CODE_BACKUP_DIR"
    chmod 700 "$CODE_BACKUP_DIR"
    RESTORE_ARCHIVE="$CODE_BACKUP_DIR/lanaxy-code-bootstrap-$(date +%Y%m%d-%H%M%S).tar.gz"
    tar -czf "$RESTORE_ARCHIVE" \
        --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        -C "$PROJECT_DIR" .
    chmod 600 "$RESTORE_ARCHIVE"
fi

say "$([[ "$IS_UPDATE" -eq 1 ]] && echo 'Installiere das Update …' || echo 'Richte LANaxy ein …')"
mkdir -p "$PROJECT_DIR"
DEPLOY_STARTED=1

# Runtime data and configuration live outside PROJECT_DIR. Keep a local .git
# directory only for developer installations; all release files are replaced.
rsync -a --delete \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$SOURCE_DIR/" "$PROJECT_DIR/"
rm -rf "$PROJECT_DIR/.github/workflows/__pycache__" 2>/dev/null || true
cd "$PROJECT_DIR"

chmod +x \
    bootstrap.sh \
    install.sh \
    update.sh \
    lanaxy.py \
    bin/lanaxy \
    web/run.py \
    scripts/setup-lanlord.sh \
    scripts/lanaxy-system-helper

if [[ "$IS_UPDATE" -eq 1 ]]; then
    ./update.sh
else
    ./install.sh
fi

DEPLOY_STARTED=0

# Keep only the five newest emergency bootstrap backups.
if [[ -d "$CODE_BACKUP_DIR" ]]; then
    mapfile -t old_backups < <(find "$CODE_BACKUP_DIR" -maxdepth 1 -type f \
        -name 'lanaxy-code-bootstrap-*.tar.gz' -printf '%T@ %p\n' \
        | sort -nr | awk 'NR>5 {$1=""; sub(/^ /,""); print}')
    if [[ "${#old_backups[@]}" -gt 0 ]]; then
        rm -f -- "${old_backups[@]}"
    fi
fi

IP_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$IP_ADDRESS" ]] || IP_ADDRESS="SERVER-IP"

say "LANaxy ist bereit."
printf 'Weboberfläche: http://%s:8090\n' "$IP_ADDRESS"
printf 'Statusprüfung:  lanaxy doctor\n'
printf 'Dokumentation:   https://lanaxy.de\n\n'
