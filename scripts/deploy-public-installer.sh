#!/usr/bin/env bash
# Deploy the public LANaxy bootstrap installer to the lanaxy.de web root.
# SPDX-License-Identifier: AGPL-3.0-or-later
set -Eeuo pipefail

SOURCE_FILE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bootstrap.sh}"
WEB_ROOT="${2:-/var/www/lanaxy}"
TARGET_FILE="$WEB_ROOT/install.sh"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Fehler: Bitte als root ausführen." >&2
    exit 1
fi

[[ -f "$SOURCE_FILE" ]] || { echo "Fehler: $SOURCE_FILE fehlt." >&2; exit 1; }
bash -n "$SOURCE_FILE"

mkdir -p "$WEB_ROOT"
temporary_file="$(mktemp "$WEB_ROOT/.install.sh.XXXXXXXX")"
trap 'rm -f "$temporary_file"' EXIT
install -o root -g root -m 0644 "$SOURCE_FILE" "$temporary_file"
mv -f "$temporary_file" "$TARGET_FILE"
trap - EXIT

echo "Installer veröffentlicht: $TARGET_FILE"
echo "Prüfung: curl -fsSL https://lanaxy.de/install.sh | head"
