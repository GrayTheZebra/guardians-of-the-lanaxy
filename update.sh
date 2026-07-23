#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/guardians-of-the-lanaxy"

apt-get update -qq
apt-get install -y -qq sudo avahi-daemon python3-gunicorn >/dev/null
CONFIG_DIR="/etc/lanaxy"
CODE_BACKUP_DIR="/etc/lanaxy/code-backups"
ROLLBACK_MARKER="/etc/lanaxy/last-successful-code-backup"

rollback() {
    local reason="$1"
    echo "Update fehlgeschlagen: $reason" >&2
    if [ -f "$ROLLBACK_MARKER" ]; then
        local archive
        archive="$(cat "$ROLLBACK_MARKER")"
        if [ -f "$archive" ]; then
            echo "Stelle letzte erfolgreiche Programmversion wieder her: $archive" >&2
            systemctl stop lanaxy-web.service lanaxy.service 2>/dev/null || true
            find "$PROJECT_DIR" -mindepth 1 -maxdepth 1                 ! -name '.git' -exec rm -rf {} +
            tar -xzf "$archive" -C "$PROJECT_DIR"
            ./scripts/setup-lanlord.sh || true
            systemctl daemon-reload
            systemctl restart lanaxy.service lanaxy-web.service || true
            echo "Rollback wurde ausgeführt." >&2
        fi
    else
        echo "Noch kein Programm-Rollback vorhanden. Das Konfigurationsbackup bleibt verfügbar." >&2
    fi
    exit 1
}

if [ "$(id -u)" -ne 0 ]; then
    echo "Fehler: Das Update muss als root ausgeführt werden." >&2
    exit 1
fi

cd "$PROJECT_DIR"

chmod +x \
    lanaxy.py \
    bin/lanaxy \
    web/run.py \
    install.sh \
    update.sh \
    scripts/setup-lanlord.sh \
    scripts/deploy-public-installer.sh

# LANLord is created before the backup so existing root-owned installations
# are migrated automatically without requiring manual permission changes.
./scripts/setup-lanlord.sh

echo "Prüfe Update-Dateien und Python-Imports ..."
required_files=(
    "lanaxy.py"
    "web/app.py"
    "web/run.py"
    "web/gunicorn.conf.py"
    "LICENSE"
    "THIRD_PARTY_LICENSES.md"
    "database.py"
    "maintenance.py"
    "notifications.py"
    "miniguard_manager.py"
    "inventory_intelligence.py"
    "assistant_planner.py"
    "system_health.py"
)
missing_files=()
for required_file in "${required_files[@]}"; do
    if [ ! -f "$required_file" ]; then
        missing_files+=("$required_file")
    fi
done

if [ "${#missing_files[@]}" -gt 0 ]; then
    echo "Fehler: Das Update wurde nicht vollständig entpackt. Folgende Dateien fehlen:" >&2
    printf '  - %s\n' "${missing_files[@]}" >&2
    echo "Die laufenden LANaxy-Dienste wurden nicht angehalten." >&2
    exit 1
fi

# Absichtlich eigenständig: Der Updater darf nicht von einem neuen Prüfmodul
# abhängen, das bei einem unvollständigen Entpacken fehlen könnte.
if ! runuser -u lanlord -- env \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$PROJECT_DIR" \
    PROJECT_DIR="$PROJECT_DIR" \
    python3 -B - <<'PY'
import importlib
import os
import py_compile
import tempfile
from pathlib import Path

project = Path(os.environ["PROJECT_DIR"])
errors = []

with tempfile.TemporaryDirectory(prefix="lanaxy-compile-") as compile_dir:
    compile_root = Path(compile_dir)
    for path in project.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(project)
        target = compile_root / relative.with_suffix(".pyc")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            py_compile.compile(str(path), cfile=str(target), doraise=True)
        except Exception as error:
            errors.append(f"Python-Syntaxfehler in {relative}: {error}")

for module_name in (
    "inventory_intelligence",
    "assistant_planner",
    "miniguard_manager",
    "maintenance",
    "notifications",
    "system_health",
    "guardians.miniguard_inventory",
    "web.run",
):
    try:
        importlib.import_module(module_name)
    except Exception as error:
        errors.append(f"Import {module_name} fehlgeschlagen: {error}")

if errors:
    raise SystemExit("\n".join(errors))
print("Release-Vorabtest erfolgreich.")
PY
then
    echo "Fehler: Der Vorabtest des Updates ist fehlgeschlagen." >&2
    echo "Die laufenden LANaxy-Dienste wurden nicht angehalten." >&2
    exit 1
fi

echo "Erstelle Sicherheitsbackup vor dem Update ..."
runuser -u lanlord -- python3 - <<'PY'
from config import load_config
from maintenance import create_backup

config = load_config("/etc/lanaxy/config.yaml")
database_path = config.get("lanaxy", {}).get(
    "database_file",
    "/var/lib/lanaxy/lanaxy.db",
)
backup = create_backup(
    database_path,
    include_database=True,
    reason="before_update",
    keep_count=int(
        config.get("lanaxy", {}).get("backup_keep_count", 20)
    ),
)
print(f"Sicherheitsbackup: {backup}")
PY

systemctl stop lanaxy-web.service lanaxy.service 2>/dev/null || true

ln -sf "$PROJECT_DIR/bin/lanaxy" /usr/bin/lanaxy
ln -sf "$PROJECT_DIR/bin/lanaxy" /usr/local/bin/lanaxy

install -o root -g root -m 0644 \
    systemd/lanaxy.service \
    /etc/systemd/system/lanaxy.service
install -o root -g root -m 0644 \
    systemd/lanaxy-web.service \
    /etc/systemd/system/lanaxy-web.service

# Re-apply ownership after all files from the update package are in place.
./scripts/setup-lanlord.sh

systemctl daemon-reload
systemctl restart lanaxy.service lanaxy-web.service

sleep 2

if ! systemctl is-active --quiet lanaxy.service; then
    echo "Fehler: lanaxy.service konnte nach der LANLord-Migration nicht starten." >&2
    journalctl -u lanaxy.service -n 80 --no-pager >&2
    echo >&2
    echo "Status des Webdienstes:" >&2
    systemctl status lanaxy-web.service --no-pager >&2 || true
    journalctl -u lanaxy-web.service -n 40 --no-pager >&2 || true
    rollback "lanaxy.service konnte nicht starten."
fi

if ! systemctl is-active --quiet lanaxy-web.service; then
    echo "Fehler: lanaxy-web.service konnte nach der LANLord-Migration nicht starten." >&2
    journalctl -u lanaxy-web.service -n 80 --no-pager >&2
    rollback "lanaxy-web.service konnte nicht starten."
fi

if ! runuser -u lanlord -- /usr/bin/lanaxy doctor; then
    echo "Fehler: lanaxy doctor meldet nach dem Update ein Problem." >&2
    systemctl status lanaxy.service lanaxy-web.service --no-pager >&2 || true
    rollback "lanaxy doctor meldet ein Problem."
fi

HEALTH_FILE="/tmp/lanaxy-health-after-update.json"
HEALTH_OK=0
for attempt in 1 2 3 4 5; do
    HTTP_STATUS="$(curl -sS --max-time 10 -o "$HEALTH_FILE" -w '%{http_code}' http://127.0.0.1:8090/health || true)"
    if [ "$HTTP_STATUS" = "200" ]; then
        HEALTH_OK=1
        break
    fi
    sleep 2
done
if [ "$HEALTH_OK" -ne 1 ]; then
    echo "Antwort des Healthchecks:" >&2
    cat "$HEALTH_FILE" >&2 2>/dev/null || true
    echo >&2
    rollback "Der HTTP-Healthcheck ist fehlgeschlagen (HTTP ${HTTP_STATUS:-000})."
fi

mkdir -p "$CODE_BACKUP_DIR"
CODE_ARCHIVE="$CODE_BACKUP_DIR/lanaxy-code-$(date +%Y%m%d-%H%M%S)-$(python3 -c 'from lanaxy import APP_VERSION; print(APP_VERSION)').tar.gz"
tar -czf "$CODE_ARCHIVE"     --exclude='__pycache__'     --exclude='*.pyc'     -C "$PROJECT_DIR" .
chmod 600 "$CODE_ARCHIVE"
echo "$CODE_ARCHIVE" > "$ROLLBACK_MARKER"
chmod 600 "$ROLLBACK_MARKER"
find "$CODE_BACKUP_DIR" -type f -name 'lanaxy-code-*.tar.gz' -printf '%T@ %p\n'     | sort -nr | awk 'NR>3 {print $2}' | xargs -r rm -f

echo
echo "LANaxy wurde aktualisiert."
echo "Beide Dienste laufen jetzt als lanlord (LANLord)."
