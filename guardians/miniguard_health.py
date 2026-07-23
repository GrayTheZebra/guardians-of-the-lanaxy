from datetime import datetime, timezone

from guardians.base import BaseGuardian
from miniguard_compat import evaluate_agent
from miniguard_manager import get_agent


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "miniguard_health",
        "name": "MiniGuard Health Guardian",
        "version": "1.0.0",
        "description": "Überwacht Erreichbarkeit, Worker, Version und Agentgesundheit eines MiniGuards",
        "icon": "shield",
        "category": "Hardware",
        "service_family": "miniguard",
        "internal": True,
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "required": True, "options": []},
        "offline_after_seconds": {"type": "number", "label": "Offline nach (Sekunden)", "default": 180, "min": 30},
        "worker_required": {"type": "checkbox", "label": "Remote-Worker muss aktiv sein", "default": True},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 30},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 2, "min": 1},
    }
    REQUIRED = ("miniguard_id",)

    def run(self):
        agent = get_agent(str(self.check.get("miniguard_id", "")))
        if agent is None:
            return self.critical(f"{self.name}: MiniGuard wurde nicht gefunden")
        details = {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
            "agent_version": agent.get("agent_version"),
            "protocol_version": agent.get("protocol_version"),
            "last_seen": agent.get("last_seen"),
            "last_poll": agent.get("last_poll"),
            "tools": agent.get("tools") or {},
            "health": agent.get("health") or {},
        }
        if not agent.get("enabled", True):
            return self.warning(f"{self.name}: MiniGuard ist deaktiviert", details=details)
        if not agent.get("registered"):
            return self.critical(f"{self.name}: MiniGuard ist nicht registriert", details=details)
        last_seen = agent.get("last_seen")
        age = None
        if last_seen:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds()
            except ValueError:
                pass
        details["last_seen_age_seconds"] = age
        offline_after = int(self.check.get("offline_after_seconds", 180) or 180)
        if age is None or age > offline_after:
            return self.critical(f"{self.name}: MiniGuard ist offline", details=details)
        compatibility = evaluate_agent(agent, "1.29.0")
        details["compatibility"] = compatibility
        if not compatibility.get("compatible"):
            return self.warning(
                f"{self.name}: MiniGuard {agent.get('agent_version') or 'unbekannt'} muss aktualisiert werden",
                details=details,
            )
        if self.check.get("worker_required", True) and not agent.get("worker_ready"):
            return self.critical(f"{self.name}: Remote-Worker ist nicht aktiv", details=details)
        health = agent.get("health") or {}
        if int(health.get("queue_failures", 0) or 0) >= 3:
            return self.warning(
                f"{self.name}: wiederholte Kommunikationsfehler ({health.get('queue_failures')})",
                details=details,
            )
        return self.ok(
            f"{self.name}: MiniGuard ist online, kompatibel und einsatzbereit",
            details=details,
        )
