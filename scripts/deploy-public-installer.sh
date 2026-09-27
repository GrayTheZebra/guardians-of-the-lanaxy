#!/usr/bin/env bash
# Deploy the public LANaxy installer and uninstaller to the lanaxy.de web root.
# SPDX-License-Identifier: AGPL-3.0-or-later
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_FILE="${1:-$REPO_ROOT/bootstrap.sh}"
WEB_ROOT="${2:-/var/www/lanaxy}"
UNINSTALL_SOURCE="${3:-$REPO_ROOT/uninstall.sh}"
TARGET_FILE="$WEB_ROOT/install.sh"
UNINSTALL_TARGET="$WEB_ROOT/uninstall.sh"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Fehler: Bitte als root ausführen." >&2
    exit 1
fi

[[ -f "$SOURCE_FILE" ]] || { echo "Fehler: $SOURCE_FILE fehlt." >&2; exit 1; }
[[ -f "$UNINSTALL_SOURCE" ]] || { echo "Fehler: $UNINSTALL_SOURCE fehlt." >&2; exit 1; }
bash -n "$SOURCE_FILE"
bash -n "$UNINSTALL_SOURCE"

mkdir -p "$WEB_ROOT"
temporary_file="$(mktemp "$WEB_ROOT/.install.sh.XXXXXXXX")"
temporary_uninstall="$(mktemp "$WEB_ROOT/.uninstall.sh.XXXXXXXX")"
trap 'rm -f "$temporary_file" "$temporary_uninstall"' EXIT

install -o root -g root -m 0644 "$SOURCE_FILE" "$temporary_file"
install -o root -g root -m 0644 "$UNINSTALL_SOURCE" "$temporary_uninstall"

mv -f "$temporary_file" "$TARGET_FILE"
mv -f "$temporary_uninstall" "$UNINSTALL_TARGET"
trap - EXIT

echo "Installer veröffentlicht:   $TARGET_FILE"
echo "Deinstaller veröffentlicht: $UNINSTALL_TARGET"
echo "Prüfung Installer:   curl -fsSL https://lanaxy.de/install.sh | head"
echo "Prüfung Deinstaller: curl -fsSL https://lanaxy.de/uninstall.sh | head"
