import glob
import os
import time
from datetime import datetime
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "backup",
        "name": "Backup Guardian",
        "version": "1.0.0",
        "description": "Prüft Alter, Größe und Anzahl vorhandener Backup-Dateien",
        "icon": "archive-check",
        "category": "Backup",
        "service_family": "backup",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 300, "min": 30},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 15, "min": 2},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 2, "min": 1},
        "pattern": {"type": "text", "label": "Backup-Datei oder Dateimuster", "required": True, "hint": "Zum Beispiel /mnt/backup/vzdump-*.zst"},
        "warning_age_hours": {"type": "number", "label": "Warning ab Alter (Stunden)", "default": 26, "min": 0},
        "critical_age_hours": {"type": "number", "label": "Critical ab Alter (Stunden)", "default": 48, "min": 0},
        "minimum_size_mb": {"type": "number", "label": "Mindestgröße des neuesten Backups (MB)", "default": 1, "min": 0},
        "retention_days": {"type": "number", "label": "Zeitraum für Mindestanzahl (Tage)", "default": 7, "min": 0},
        "minimum_count": {"type": "number", "label": "Mindestens vorhandene Backups im Zeitraum", "default": 1, "min": 1},
        "ignore_partial": {"type": "checkbox", "label": "Temporäre und unvollständige Dateien ignorieren", "default": True},
    }
    REQUIRED = ("pattern",)

    @staticmethod
    def _matches(pattern, ignore_partial=True):
        ignored = (".tmp", ".part", ".partial", ".incomplete")
        output = []
        for raw in glob.glob(os.path.expanduser(pattern)):
            path = Path(raw)
            if not path.is_file():
                continue
            if ignore_partial and (path.name.startswith(".") or path.name.lower().endswith(ignored)):
                continue
            output.append(path)
        return output

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("backup")
        start = time.monotonic()
        pattern = str(self.check["pattern"]).strip()
        matches = self._matches(pattern, bool(self.check.get("ignore_partial", True)))
        details = {"guardian": self.GUARDIAN, "pattern": pattern, "total_matches": len(matches)}
        if not matches:
            return self.critical(f"{self.name}: Kein Backup gefunden", details=details)
        now = time.time()
        newest = max(matches, key=lambda p: p.stat().st_mtime)
        stat = newest.stat()
        age_hours = max(0.0, (now - stat.st_mtime) / 3600)
        size_mb = stat.st_size / 1048576
        retention_days = float(self.check.get("retention_days", 7) or 0)
        recent = [p for p in matches if not retention_days or now - p.stat().st_mtime <= retention_days * 86400]
        details.update(newest=str(newest), newest_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(), age_hours=round(age_hours, 2), size_bytes=stat.st_size, size_mb=round(size_mb, 2), recent_count=len(recent), retention_days=retention_days)
        minimum_size = float(self.check.get("minimum_size_mb", 1) or 0)
        if minimum_size and size_mb < minimum_size:
            return self.critical(f"{self.name}: Neuestes Backup ist mit {size_mb:.1f} MB kleiner als {minimum_size:g} MB", details=details)
        minimum_count = int(self.check.get("minimum_count", 1) or 1)
        if len(recent) < minimum_count:
            return self.critical(f"{self.name}: Nur {len(recent)} von mindestens {minimum_count} Backups im Prüfzeitraum vorhanden", details=details)
        critical_age = float(self.check.get("critical_age_hours", 48) or 0)
        warning_age = float(self.check.get("warning_age_hours", 26) or 0)
        response_ms = int((time.monotonic() - start) * 1000)
        if critical_age and age_hours >= critical_age:
            return self.critical(f"{self.name}: Neuestes Backup ist {age_hours:.1f} Stunden alt", response_ms, details)
        if warning_age and age_hours >= warning_age:
            return self.warning(f"{self.name}: Neuestes Backup ist {age_hours:.1f} Stunden alt", response_ms, details)
        return self.ok(f"{self.name}: Neuestes Backup ist {age_hours:.1f} Stunden alt ({size_mb:.1f} MB)", response_ms, details)
