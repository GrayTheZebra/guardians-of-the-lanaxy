import glob
import os
import time
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "file_age", "name": "Dateialter Guardian", "version": "1.1.0",
        "description": "Prüft Existenz, Alter und Größe einer Datei oder der neuesten passenden Datei",
        "icon": "file-clock", "category": "System", "service_family": "filesystem",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True, "hint": "Der MiniGuard muss online sein und diesen Check unterstützen."},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "path": {"type": "text", "label": "Datei oder Dateimuster", "required": True, "hint": "Beispiel: /backup/db-*.sql.gz"},
        "warning_age_minutes": {"type": "number", "label": "Warning ab Alter (Minuten)", "default": 60, "min": 0},
        "critical_age_minutes": {"type": "number", "label": "Critical ab Alter (Minuten)", "default": 120, "min": 0},
        "minimum_size_bytes": {"type": "number", "label": "Mindestgröße (Bytes)", "default": 0, "min": 0},
    }
    REQUIRED = ("path",)

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("file_age")
        started = time.monotonic()
        pattern = str(self.check["path"]).strip()
        matches = [Path(p) for p in glob.glob(os.path.expanduser(pattern)) if Path(p).is_file()]
        details = {"guardian": self.GUARDIAN, "pattern": pattern, "matches": len(matches)}
        if not matches:
            return self.critical(f"{self.name}: Keine passende Datei gefunden", details=details)
        target = max(matches, key=lambda p: p.stat().st_mtime)
        stat = target.stat()
        age_seconds = max(0.0, time.time() - stat.st_mtime)
        age_minutes = age_seconds / 60
        details.update(path=str(target), size_bytes=stat.st_size, modified_at=stat.st_mtime, age_seconds=round(age_seconds, 1))
        minimum = int(self.check.get("minimum_size_bytes", 0) or 0)
        if minimum and stat.st_size < minimum:
            return self.critical(f"{self.name}: Datei ist mit {stat.st_size} Bytes kleiner als {minimum} Bytes", details=details)
        critical = float(self.check.get("critical_age_minutes", 120) or 0)
        warning = float(self.check.get("warning_age_minutes", 60) or 0)
        ms = int((time.monotonic() - started) * 1000)
        if critical and age_minutes >= critical:
            return self.critical(f"{self.name}: Datei ist {age_minutes:.1f} Minuten alt", ms, details)
        if warning and age_minutes >= warning:
            return self.warning(f"{self.name}: Datei ist {age_minutes:.1f} Minuten alt", ms, details)
        return self.ok(f"{self.name}: {target.name} ist {age_minutes:.1f} Minuten alt", ms, details)
