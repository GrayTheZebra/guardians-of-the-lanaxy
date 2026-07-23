import subprocess
import time

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "systemd_service",
        "name": "Systemd Service Guardian",
        "version": "1.1.0",
        "description": "Überwacht Zustand, Substate, Laufzeit und Neustarts einer systemd-Unit",
        "icon": "server",
        "category": "System",
        "service_family": "systemd",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True, "hint": "Der MiniGuard muss online sein und diesen Check unterstützen."},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 30, "min": 5},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "unit": {"type": "text", "label": "Systemd-Unit", "required": True},
        "expected_active_state": {
            "type": "select", "label": "Erwarteter Zustand", "default": "active",
            "options": [
                {"value": "active", "label": "active"},
                {"value": "inactive", "label": "inactive"},
                {"value": "any", "label": "Beliebig (nur Existenz prüfen)"},
            ],
        },
        "expected_sub_state": {"type": "text", "label": "Erwarteter Substate", "help": "Optional, zum Beispiel running oder exited"},
        "require_enabled": {"type": "checkbox", "label": "Unit muss aktiviert sein", "default": False},
        "minimum_uptime_seconds": {"type": "number", "label": "Minimale Laufzeit (Sekunden)", "default": 0, "min": 0},
        "warning_restart_count": {"type": "number", "label": "Warnung ab Neustartzähler", "default": 3, "min": 0},
        "critical_restart_count": {"type": "number", "label": "Critical ab Neustartzähler", "default": 10, "min": 0},
    }

    REQUIRED = ("unit",)

    def _show(self, unit):
        properties = [
            "LoadState", "ActiveState", "SubState", "UnitFileState",
            "NRestarts", "ActiveEnterTimestampMonotonic", "Description",
            "Result", "ExecMainStatus",
        ]
        command = ["systemctl", "show", unit, "--no-pager"]
        for prop in properties:
            command.extend(["--property", prop])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        values = {}
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return completed, values

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("systemd")
        unit = str(self.check["unit"]).strip()
        if "." not in unit:
            unit += ".service"

        started = time.monotonic()
        details = {"guardian": self.GUARDIAN, "unit": unit}
        try:
            completed, values = self._show(unit)
        except FileNotFoundError:
            return self.critical(f"{self.name}: systemctl ist nicht verfügbar", details=details)
        except subprocess.TimeoutExpired:
            return self.critical(f"{self.name}: systemctl-Timeout", int(self.timeout * 1000), details)

        response_ms = int((time.monotonic() - started) * 1000)
        details.update(values)
        details["response_ms"] = response_ms
        details["systemctl_returncode"] = completed.returncode

        if values.get("LoadState") == "not-found" or not values:
            return self.critical(f"{self.name}: Unit {unit} wurde nicht gefunden", response_ms, details)

        active = values.get("ActiveState", "unknown")
        sub = values.get("SubState", "unknown")
        expected_active = str(self.check.get("expected_active_state", "active"))
        if active == "failed":
            return self.critical(f"{self.name}: {unit} ist fehlgeschlagen", response_ms, details)
        if expected_active != "any" and active != expected_active:
            return self.critical(
                f"{self.name}: {unit} ist {active}/{sub}, erwartet wird {expected_active}",
                response_ms,
                details,
            )

        expected_sub = str(self.check.get("expected_sub_state", "")).strip()
        if expected_sub and sub != expected_sub:
            return self.critical(
                f"{self.name}: Substate ist {sub}, erwartet wird {expected_sub}",
                response_ms,
                details,
            )

        if bool(self.check.get("require_enabled", False)):
            enabled_states = {"enabled", "enabled-runtime", "static", "indirect", "generated"}
            if values.get("UnitFileState") not in enabled_states:
                return self.warning(
                    f"{self.name}: {unit} ist nicht dauerhaft aktiviert",
                    response_ms,
                    details,
                )

        try:
            restarts = int(values.get("NRestarts", 0) or 0)
        except ValueError:
            restarts = 0
        critical_restarts = int(self.check.get("critical_restart_count", 10) or 0)
        warning_restarts = int(self.check.get("warning_restart_count", 3) or 0)
        if critical_restarts and restarts >= critical_restarts:
            return self.critical(
                f"{self.name}: Neustartzähler kritisch ({restarts})",
                response_ms,
                details,
            )
        if warning_restarts and restarts >= warning_restarts:
            return self.warning(
                f"{self.name}: erhöhter Neustartzähler ({restarts})",
                response_ms,
                details,
            )

        minimum_uptime = int(self.check.get("minimum_uptime_seconds", 0) or 0)
        entered_us = int(values.get("ActiveEnterTimestampMonotonic", 0) or 0)
        if minimum_uptime and active == "active" and entered_us:
            uptime = max(0, int(time.clock_gettime(time.CLOCK_BOOTTIME) - entered_us / 1_000_000))
            details["uptime_seconds"] = uptime
            if uptime < minimum_uptime:
                return self.warning(
                    f"{self.name}: Dienst läuft erst seit {uptime} Sekunden",
                    response_ms,
                    details,
                )

        return self.ok(
            f"{self.name}: {unit} ist {active}/{sub}",
            response_ms,
            details,
        )
