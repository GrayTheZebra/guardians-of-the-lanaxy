from guardians.base import BaseGuardian
from utils.network import ping, tcp_check


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "tcp_port",
        "name": "TCP Port Guardian",
        "version": "1.0.0",
        "description": "Prüft Erreichbarkeit und TCP-Port eines Dienstes",
        "icon": "network",
        "category": "Netzwerk",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 30, "min": 2},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 3, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "host": {"type": "text", "label": "Host oder IP", "required": True},
        "port": {"type": "number", "label": "TCP-Port", "required": True},
        "ping": {"type": "checkbox", "label": "Ping zusätzlich prüfen", "default": True},
    }

    REQUIRED = ("host", "port")

    def run(self):
        host = self.check["host"]
        port = int(self.check["port"])
        ping_enabled = bool(self.check.get("ping", True))

        details = {
            "guardian": self.GUARDIAN,
            "host": host,
            "port": port,
        }

        if ping_enabled:
            ping_result = ping(host, self.timeout)
            details["ping"] = ping_result

            if not ping_result["ok"]:
                return self.result(
                    "critical",
                    2,
                    f"{self.name} ist per Ping nicht erreichbar",
                    int(ping_result["ms"]),
                    details,
                )

        tcp_result = tcp_check(host, port, self.timeout)
        details["tcp"] = tcp_result

        if not tcp_result["ok"]:
            return self.result(
                "critical",
                2,
                f"{self.name} Port {port} ist nicht erreichbar",
                int(tcp_result["ms"]),
                details,
            )

        return self.result(
            "ok",
            0,
            f"{self.name} Port {port} ist erreichbar",
            int(tcp_result["ms"]),
            details,
        )
