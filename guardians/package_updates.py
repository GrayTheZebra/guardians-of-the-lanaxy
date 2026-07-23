from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "package_updates",
        "name": "Updates / Neustart Guardian",
        "version": "1.1.0",
        "description": "Erkennt verfügbare Paketupdates und notwendige Neustarts",
        "icon": "settings",
        "category": "System",
        "service_family": "updates",
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
        "warning_updates": {"type": "number", "label": "Warning ab Anzahl Updates", "default": 1, "min": 0},
        "critical_updates": {"type": "number", "label": "Critical ab Anzahl Updates", "default": 30, "min": 0},
        "reboot_is_critical": {"type": "checkbox", "label": "Notwendiger Neustart ist Critical", "default": True},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 21600, "min": 300},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 60, "min": 10},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 2, "min": 1},
    }
    REQUIRED = ()

    def run(self):
        if str(self.check.get("execution_source", "miniguard")) == "miniguard":
            return self.remote("package_updates")
        from miniguard_agent import check_package_updates
        result = check_package_updates(self.check)
        levels = {"ok": 0, "warning": 1, "critical": 2, "unknown": 2}
        return self.result(result["status"], levels.get(result["status"], 2), result["message"], result.get("duration_ms", 0), result.get("details", {}))
