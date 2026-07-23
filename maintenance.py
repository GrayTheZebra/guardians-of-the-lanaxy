import io
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import yaml


CONFIG_FILE = Path("/etc/lanaxy/config.yaml")
BACKUP_DIR = Path("/etc/lanaxy/backups")
GUARDIAN_DIR = Path("/etc/lanaxy/guardians.d")
BEACON_DIR = Path("/etc/lanaxy/beacons.d")
PORTAL_DIR = Path("/etc/lanaxy/portals.d")
DATA_DIR = Path("/var/lib/lanaxy")
STATE_FILE = DATA_DIR / "state.json"
NOTIFICATION_STATUS_FILE = DATA_DIR / "notification-status.json"

SECRET_KEYS = {
    "password",
    "password_hash",
    "token",
    "bot_token",
    "bearer_token",
    "api_key",
    "secret",
    "webhook_url",
}


def timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def human_size(size):
    size = int(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def file_size(path):
    path = Path(path)
    return path.stat().st_size if path.exists() else 0


def directory_size(path):
    path = Path(path)
    if not path.exists():
        return 0
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file()
    )


def database_stats(database_path):
    path = Path(database_path)
    result = {
        "path": str(path),
        "size": file_size(path),
        "size_human": human_size(file_size(path)),
        "events": 0,
        "metrics": 0,
        "oldest_event": "",
        "newest_event": "",
        "oldest_metric": "",
        "newest_metric": "",
    }

    if not path.exists():
        return result

    try:
        connection = sqlite3.connect(path)
        for table in ("events", "metrics"):
            result[table] = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            bounds = connection.execute(
                f"SELECT MIN(timestamp), MAX(timestamp) FROM {table}"
            ).fetchone()
            singular = "event" if table == "events" else "metric"
            result[f"oldest_{singular}"] = bounds[0] or ""
            result[f"newest_{singular}"] = bounds[1] or ""
    except sqlite3.Error:
        result["error"] = "Database statistics could not be read."
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return result


def add_path_to_zip(archive, source, target):
    source = Path(source)
    if not source.exists():
        return

    if source.is_file():
        archive.write(source, target)
        return

    for item in sorted(source.rglob("*")):
        if item.is_file():
            archive.write(item, str(Path(target) / item.relative_to(source)))


def prune_backups(keep=20):
    backups = sorted(
        BACKUP_DIR.glob("lanaxy-backup-*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in backups[max(1, int(keep)):]:
        path.unlink(missing_ok=True)


def add_database_snapshot(archive, database_path):
    source_path = Path(database_path)
    if not source_path.exists():
        return

    with tempfile.TemporaryDirectory(
        prefix="lanaxy-db-backup-"
    ) as temporary:
        snapshot = Path(temporary) / "lanaxy.db"
        source = sqlite3.connect(source_path, timeout=30)
        destination = sqlite3.connect(snapshot)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        archive.write(snapshot, "data/lanaxy.db")


def create_backup(
    database_path,
    include_database=True,
    reason="manual",
    keep_count=20,
):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"lanaxy-backup-{timestamp()}.zip"
    target = BACKUP_DIR / filename
    temporary = target.with_suffix(".zip.tmp")

    manifest = {
        "format": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
        "reason": reason,
        "includes_database": bool(include_database),
        "application": "Guardians of the LANaxy",
    }

    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        add_path_to_zip(archive, CONFIG_FILE, "config/config.yaml")
        add_path_to_zip(archive, GUARDIAN_DIR, "plugins/guardians")
        add_path_to_zip(archive, BEACON_DIR, "plugins/beacons")
        add_path_to_zip(archive, PORTAL_DIR, "plugins/portals")
        add_path_to_zip(archive, STATE_FILE, "data/state.json")
        add_path_to_zip(
            archive,
            NOTIFICATION_STATUS_FILE,
            "data/notification-status.json",
        )
        if include_database:
            add_database_snapshot(archive, database_path)

    os.chmod(temporary, 0o600)
    temporary.replace(target)
    prune_backups(keep_count)
    for stale in BACKUP_DIR.glob("*.tmp"):
        stale.unlink(missing_ok=True)
    return target


def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    result = []

    for path in sorted(
        BACKUP_DIR.glob("lanaxy-backup-*.zip"),
        reverse=True,
    ):
        item = {
            "name": path.name,
            "path": path,
            "size": path.stat().st_size,
            "size_human": human_size(path.stat().st_size),
            "modified": datetime.fromtimestamp(
                path.stat().st_mtime
            ).isoformat(timespec="seconds"),
            "includes_database": None,
            "reason": "",
        }
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )
                item["includes_database"] = manifest.get(
                    "includes_database"
                )
                item["reason"] = manifest.get("reason", "")
                item["created_at"] = manifest.get("created_at", "")
        except Exception:
            item["invalid"] = True
        result.append(item)

    return result


def safe_member(member):
    path = Path(member)
    if path.is_absolute() or ".." in path.parts:
        return False

    fixed_entries = {
        "manifest.json",
        "config/config.yaml",
        "data/state.json",
        "data/notification-status.json",
        "data/lanaxy.db",
    }
    return (
        member in fixed_entries
        or member.startswith("plugins/guardians/")
        or member.startswith("plugins/beacons/")
    )


def validate_backup(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            raise ValueError("Backup manifest is missing.")
        manifest = json.loads(
            archive.read("manifest.json").decode("utf-8")
        )
        if manifest.get("format") != 1:
            raise ValueError("Unsupported backup format.")
        if "config/config.yaml" not in names:
            raise ValueError("Backup does not contain a configuration.")
        for name in names:
            if not safe_member(name):
                raise ValueError(f"Unsafe backup entry: {name}")
        config = yaml.safe_load(
            archive.read("config/config.yaml").decode("utf-8")
        )
        if not isinstance(config, dict):
            raise ValueError("Backup configuration is invalid.")
        if not isinstance(config.get("mqtt"), dict):
            raise ValueError("Backup MQTT configuration is invalid.")
        if not isinstance(config.get("checks", []), list):
            raise ValueError("Backup Guardian configuration is invalid.")
        return manifest


def restore_backup(
    backup_path,
    database_path,
    restore_database=True,
    keep_count=20,
):
    backup_path = Path(backup_path)
    manifest = validate_backup(backup_path)

    safety_backup = create_backup(
        database_path,
        include_database=True,
        reason="before_restore",
        keep_count=keep_count,
    )

    with tempfile.TemporaryDirectory(prefix="lanaxy-restore-") as temp:
        temp_path = Path(temp)
        with zipfile.ZipFile(backup_path) as archive:
            archive.extractall(temp_path)

        config_source = temp_path / "config/config.yaml"
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_source, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)

        for source, destination in (
            (temp_path / "plugins/guardians", GUARDIAN_DIR),
            (temp_path / "plugins/beacons", BEACON_DIR),
            (temp_path / "plugins/portals", PORTAL_DIR),
        ):
            destination.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=True,
                )

        optional_files = (
            (temp_path / "data/state.json", STATE_FILE),
            (
                temp_path / "data/notification-status.json",
                NOTIFICATION_STATUS_FILE,
            ),
        )
        for source, destination in optional_files:
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

        database_source = temp_path / "data/lanaxy.db"
        if restore_database and database_source.exists():
            database_target = Path(database_path)
            database_target.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(database_target) + suffix).unlink(
                    missing_ok=True
                )
            shutil.copy2(database_source, database_target)
            os.chmod(database_target, 0o600)

    return {
        "manifest": manifest,
        "safety_backup": safety_backup,
    }


def redact(value, key=""):
    if isinstance(value, dict):
        result = {}
        for child_key, child_value in value.items():
            normalized = child_key.lower()
            if (
                normalized in SECRET_KEYS
                or normalized.endswith("_password")
                or normalized.endswith("_token")
                or normalized.endswith("_secret")
            ):
                result[child_key] = "***REDACTED***"
            else:
                result[child_key] = redact(child_value, child_key)
        return result
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def redact_text(text):
    patterns = (
        (
            r"(?i)(password|passwd|token|secret|authorization)"
            r"(\s*[:=]\s*)([^\s]+)",
            r"\1\2***REDACTED***",
        ),
        (
            r"https://api\.telegram\.org/bot[^/\s]+",
            "https://api.telegram.org/bot***REDACTED***",
        ),
        (
            r"https://(?:discord(?:app)?\.com)/api/webhooks/[^\s]+",
            "https://discord.com/api/webhooks/***REDACTED***",
        ),
    )
    result = text
    for pattern, replacement in patterns:
        result = __import__("re").sub(
            pattern,
            replacement,
            result,
        )
    return result


def command_output(command):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        return redact_text(output[-30000:])
    except Exception as error:
        return f"Command failed: {error}"


def create_diagnostic_bundle(
    config,
    database_path,
    app_version,
):
    memory = io.BytesIO()
    redacted_config = redact(config)
    db_stats = database_stats(database_path)

    system_info = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": app_version,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "database": db_stats,
        "custom_guardians_size": human_size(
            directory_size(GUARDIAN_DIR)
        ),
        "custom_beacons_size": human_size(
            directory_size(BEACON_DIR)
        ),
    }

    with zipfile.ZipFile(
        memory,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "system.json",
            json.dumps(system_info, ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "config-redacted.yaml",
            yaml.safe_dump(
                redacted_config,
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        archive.writestr(
            "lanaxy-doctor.txt",
            command_output(["/usr/bin/lanaxy", "doctor"]),
        )
        archive.writestr(
            "lanaxy-service.txt",
            command_output(
                [
                    "/usr/bin/systemctl",
                    "status",
                    "lanaxy.service",
                    "--no-pager",
                ]
            ),
        )
        archive.writestr(
            "lanaxy-web-service.txt",
            command_output(
                [
                    "/usr/bin/systemctl",
                    "status",
                    "lanaxy-web.service",
                    "--no-pager",
                ]
            ),
        )
        archive.writestr(
            "lanaxy-journal.txt",
            command_output(
                [
                    "/usr/bin/journalctl",
                    "-u",
                    "lanaxy.service",
                    "-n",
                    "300",
                    "--no-pager",
                    "--quiet",
                ]
            ),
        )
        archive.writestr(
            "lanaxy-web-journal.txt",
            command_output(
                [
                    "/usr/bin/journalctl",
                    "-u",
                    "lanaxy-web.service",
                    "-n",
                    "300",
                    "--no-pager",
                    "--quiet",
                ]
            ),
        )

        if STATE_FILE.exists():
            archive.write(STATE_FILE, "state.json")

    memory.seek(0)
    return memory
