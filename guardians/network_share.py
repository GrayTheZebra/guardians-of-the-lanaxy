import os
import subprocess
import tempfile
import time
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "network_share",
        "name": "SMB/NFS Guardian",
        "version": "1.0.0",
        "description": "Prüft Erreichbarkeit, Mounttyp sowie Lese- und Schreibzugriff einer SMB- oder NFS-Freigabe",
        "icon": "folder-network",
        "category": "Storage",
        "service_family": "network_share",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 15, "min": 2},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "path": {"type": "text", "label": "Mountpoint", "required": True, "hint": "Zum Beispiel /mnt/nas"},
        "expected_fs_types": {"type": "text", "label": "Erwartete Dateisystemtypen", "default": "cifs,nfs,nfs4", "hint": "Kommasepariert; leer lassen, um den Typ nicht einzuschränken"},
        "read_test": {"type": "checkbox", "label": "Verzeichnisinhalt lesen", "default": True},
        "write_test": {"type": "checkbox", "label": "Kontrollierten Schreibtest durchführen", "default": False},
        "warning_response_ms": {"type": "number", "label": "Warning ab Zugriffszeit (ms)", "default": 1000, "min": 0},
        "critical_response_ms": {"type": "number", "label": "Critical ab Zugriffszeit (ms)", "default": 5000, "min": 0},
    }
    REQUIRED = ("path",)

    @staticmethod
    def _mount_info(path, timeout):
        cp = subprocess.run(["findmnt", "-J", "-T", str(path)], capture_output=True, text=True, timeout=timeout, check=False)
        if cp.returncode != 0:
            return None
        import json
        data = json.loads(cp.stdout or "{}")
        rows = data.get("filesystems") or []
        return rows[0] if rows else None

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("network_share")
        start = time.monotonic()
        path = Path(str(self.check["path"]).strip())
        details = {"guardian": self.GUARDIAN, "path": str(path)}
        try:
            mount = self._mount_info(path, self.timeout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            details["error"] = str(error)
            return self.critical(f"{self.name}: Mountinformation konnte nicht gelesen werden", details=details)
        if not mount or os.path.abspath(str(mount.get("target", ""))) != os.path.abspath(str(path)):
            details["detected_mount"] = mount
            return self.critical(f"{self.name}: {path} ist nicht als eigener Mountpoint eingehängt", details=details)
        fs_type = str(mount.get("fstype", ""))
        details.update(source=mount.get("source"), target=mount.get("target"), fs_type=fs_type, options=mount.get("options"))
        expected = {v.strip().lower() for v in str(self.check.get("expected_fs_types", "")).split(",") if v.strip()}
        if expected and fs_type.lower() not in expected:
            return self.critical(f"{self.name}: Dateisystemtyp ist {fs_type}, erwartet wird {', '.join(sorted(expected))}", details=details)
        try:
            if self.check.get("read_test", True):
                next(os.scandir(path), None)
                details["read_test"] = "ok"
            if self.check.get("write_test"):
                with tempfile.NamedTemporaryFile(dir=path, prefix=".lanaxy-share-test-", delete=True) as handle:
                    handle.write(b"LANaxy")
                    handle.flush()
                    os.fsync(handle.fileno())
                details["write_test"] = "ok"
        except OSError as error:
            details["io_error"] = str(error)
            return self.critical(f"{self.name}: Zugriffstest auf {path} fehlgeschlagen: {error}", details=details)
        response_ms = int((time.monotonic() - start) * 1000)
        details["response_ms"] = response_ms
        critical_ms = int(self.check.get("critical_response_ms", 5000) or 0)
        warning_ms = int(self.check.get("warning_response_ms", 1000) or 0)
        if critical_ms and response_ms >= critical_ms:
            return self.critical(f"{self.name}: Netzwerkfreigabe reagiert sehr langsam ({response_ms} ms)", response_ms, details)
        if warning_ms and response_ms >= warning_ms:
            return self.warning(f"{self.name}: Netzwerkfreigabe reagiert langsam ({response_ms} ms)", response_ms, details)
        return self.ok(f"{self.name}: {fs_type}-Freigabe ist erreichbar", response_ms, details)
