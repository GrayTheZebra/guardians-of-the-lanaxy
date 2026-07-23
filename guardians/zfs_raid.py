import re
import shutil
import subprocess
import time
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "zfs_raid",
        "name": "ZFS / RAID Guardian",
        "version": "1.0.1",
        "description": "Prüft ZFS-Pools oder Linux-MD-RAIDs auf Fehler und Degradierung",
        "icon": "hard-drive",
        "category": "Hardware",
        "service_family": "storage",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "miniguard", "options": [
            {"value": "local", "label": "Dieses LANaxy-System"},
            {"value": "miniguard", "label": "MiniGuard"},
        ]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True},
        "mode": {"type": "select", "label": "RAID-Typ", "default": "zfs", "options": [
            {"value": "zfs", "label": "ZFS-Pool"},
            {"value": "mdraid", "label": "Linux MD RAID"},
        ]},
        "pool": {"type": "text", "label": "Pool- oder RAID-Name", "hint": "Bei ZFS zum Beispiel tank; bei MD RAID optional md0.", "required": False},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 300, "min": 30},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 20, "min": 5},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 2, "min": 1},
    }
    REQUIRED = ()

    def run(self):
        if str(self.check.get("execution_source", "miniguard")) == "miniguard":
            return self.remote("zfs_raid")
        started = time.monotonic()
        mode = self.check.get("mode", "zfs")
        pool = str(self.check.get("pool", "")).strip()
        if mode == "zfs":
            if not shutil.which("zpool"):
                return self.unknown(f"{self.name}: zpool ist nicht installiert")
            command = ["zpool", "status", "-x"]
            if pool:
                command.append(pool)
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
            output = (result.stdout + "\n" + result.stderr).strip()
            details = {"mode": mode, "pool": pool or None, "output": output}
            if result.returncode != 0:
                return self.critical(f"{self.name}: ZFS-Prüfung fehlgeschlagen", details=details)
            normalized = " ".join(output.lower().split())
            healthy = (
                normalized == "all pools are healthy"
                or normalized.endswith(" is healthy")
                or bool(re.search(r"(?:^|\s)pool\s+[\'\"]?.+?[\'\"]?\s+is\s+healthy(?:$|\s)", normalized))
            )
            details["normalized_output"] = normalized
            details["healthy_detected"] = healthy
            if not healthy:
                return self.critical(f"{self.name}: ZFS-Pool ist nicht gesund", details=details)
            return self.ok(f"{self.name}: ZFS-Pool ist gesund", int((time.monotonic()-started)*1000), details)

        mdstat = Path("/proc/mdstat")
        if not mdstat.exists():
            return self.unknown(f"{self.name}: /proc/mdstat ist nicht vorhanden")
        output = mdstat.read_text(encoding="utf-8", errors="replace")
        details = {"mode": mode, "pool": pool or None, "output": output}
        blocks = output.split("\n\n")
        relevant = [block for block in blocks if not pool or pool in block]
        if not relevant:
            return self.critical(f"{self.name}: MD-RAID {pool or ''} wurde nicht gefunden", details=details)
        joined = "\n".join(relevant)
        if "_" in joined or "faulty" in joined.lower() or "inactive" in joined.lower():
            return self.critical(f"{self.name}: MD-RAID ist degradiert", details=details)
        return self.ok(f"{self.name}: MD-RAID ist aktiv", int((time.monotonic()-started)*1000), details)
