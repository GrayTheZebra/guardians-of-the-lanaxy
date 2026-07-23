import os
import subprocess
import tempfile
import time
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "storage",
        "name": "Speicherplatz Guardian",
        "version": "1.1.0",
        "description": "Überwacht Mountpoint, freien Speicher, Inodes und Schreibbarkeit",
        "icon": "hard-drive",
        "category": "System",
        "service_family": "storage",
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
        "path": {"type": "text", "label": "Pfad oder Mountpoint", "required": True, "default": "/"},
        "require_mountpoint": {"type": "checkbox", "label": "Pfad muss eigener Mountpoint sein", "default": False},
        "warning_free_percent": {"type": "number", "label": "Warning unter frei (%)", "default": 15, "min": 0},
        "critical_free_percent": {"type": "number", "label": "Critical unter frei (%)", "default": 5, "min": 0},
        "warning_free_mb": {"type": "number", "label": "Warning unter frei (MB)", "default": 0, "min": 0},
        "critical_free_mb": {"type": "number", "label": "Critical unter frei (MB)", "default": 0, "min": 0},
        "warning_free_inodes_percent": {"type": "number", "label": "Warning unter freie Inodes (%)", "default": 10, "min": 0},
        "critical_free_inodes_percent": {"type": "number", "label": "Critical unter freie Inodes (%)", "default": 3, "min": 0},
        "write_test": {"type": "checkbox", "label": "Kontrollierten Schreibtest durchführen", "default": False},
    }

    REQUIRED = ("path",)

    @staticmethod
    def _mount_details(path, timeout):
        try:
            result = subprocess.run(
                ["findmnt", "-T", path, "-n", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(None, 3)
                return {
                    "target": parts[0] if len(parts) > 0 else "",
                    "source": parts[1] if len(parts) > 1 else "",
                    "filesystem": parts[2] if len(parts) > 2 else "",
                    "options": parts[3] if len(parts) > 3 else "",
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return {}

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("storage")
        started = time.monotonic()
        path = Path(str(self.check["path"])).expanduser()
        details = {"guardian": self.GUARDIAN, "path": str(path)}

        if not path.exists():
            return self.critical(f"{self.name}: Pfad {path} existiert nicht", details=details)
        if not path.is_dir():
            return self.critical(f"{self.name}: {path} ist kein Verzeichnis", details=details)
        if bool(self.check.get("require_mountpoint", False)) and not os.path.ismount(path):
            return self.critical(f"{self.name}: {path} ist kein eigener Mountpoint", details=details)

        mount = self._mount_details(str(path), self.timeout)
        details["mount"] = mount
        options = {option for option in mount.get("options", "").split(",") if option}
        # A hardened systemd service (for example ProtectSystem=strict) may
        # expose otherwise writable host mounts as read-only inside LANaxy's
        # private mount namespace. Therefore a visible ``ro`` flag alone is
        # not a reliable indication that the underlying filesystem is broken.
        # Keep the information in the details and use the optional write test
        # for an authoritative check of LANaxy's actual write access.
        details["read_only_visible"] = "ro" in options

        try:
            stats = os.statvfs(path)
        except OSError as error:
            details["error"] = str(error)
            return self.critical(f"{self.name}: Speicherstatistik konnte nicht gelesen werden", details=details)

        total_bytes = stats.f_blocks * stats.f_frsize
        free_bytes = stats.f_bavail * stats.f_frsize
        used_bytes = max(0, total_bytes - stats.f_bfree * stats.f_frsize)
        free_percent = (free_bytes / total_bytes * 100) if total_bytes else 0.0
        inode_total = stats.f_files
        inode_free = stats.f_favail
        inode_free_percent = (inode_free / inode_total * 100) if inode_total else 100.0
        free_mb = free_bytes / (1024 * 1024)

        details.update({
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "free_percent": round(free_percent, 2),
            "inode_total": inode_total,
            "inode_free": inode_free,
            "inode_free_percent": round(inode_free_percent, 2),
        })

        if bool(self.check.get("write_test", False)):
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".lanaxy-write-test-",
                    dir=path,
                    delete=True,
                ) as handle:
                    handle.write(b"LANaxy")
                    handle.flush()
                    os.fsync(handle.fileno())
                details["write_test"] = "ok"
            except OSError as error:
                details["write_test"] = "failed"
                details["write_error"] = str(error)
                return self.critical(f"{self.name}: Schreibtest fehlgeschlagen", details=details)

        response_ms = int((time.monotonic() - started) * 1000)
        critical_percent = int(self.check.get("critical_free_percent", 5) or 0)
        warning_percent = int(self.check.get("warning_free_percent", 15) or 0)
        critical_mb = int(self.check.get("critical_free_mb", 0) or 0)
        warning_mb = int(self.check.get("warning_free_mb", 0) or 0)
        critical_inodes = int(self.check.get("critical_free_inodes_percent", 3) or 0)
        warning_inodes = int(self.check.get("warning_free_inodes_percent", 10) or 0)

        critical_reasons = []
        warning_reasons = []
        if critical_percent and free_percent <= critical_percent:
            critical_reasons.append(f"nur {free_percent:.1f} % frei")
        elif warning_percent and free_percent <= warning_percent:
            warning_reasons.append(f"nur {free_percent:.1f} % frei")
        if critical_mb and free_mb <= critical_mb:
            critical_reasons.append(f"nur {free_mb:.0f} MB frei")
        elif warning_mb and free_mb <= warning_mb:
            warning_reasons.append(f"nur {free_mb:.0f} MB frei")
        if critical_inodes and inode_free_percent <= critical_inodes:
            critical_reasons.append(f"nur {inode_free_percent:.1f} % Inodes frei")
        elif warning_inodes and inode_free_percent <= warning_inodes:
            warning_reasons.append(f"nur {inode_free_percent:.1f} % Inodes frei")

        if critical_reasons:
            return self.critical(f"{self.name}: " + ", ".join(critical_reasons), response_ms, details)
        if warning_reasons:
            return self.warning(f"{self.name}: " + ", ".join(warning_reasons), response_ms, details)

        return self.ok(
            f"{self.name}: {free_percent:.1f} % ({free_mb:.0f} MB) frei",
            response_ms,
            details,
        )
