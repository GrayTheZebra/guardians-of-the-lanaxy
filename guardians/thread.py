from guardians.base import BaseGuardian
from utils.http import get_json
from utils.network import ping, tcp_check


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "thread",
        "name": "Thread Guardian",
        "version": "1.0.0",
        "description": "Überwacht Thread-Dongle, TCP-Port und OTBR REST Dataset",
        "icon": "thread",
        "category": "Smart Home",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 10, "min": 2},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 3, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "dongle_ip": {"type": "text", "label": "Thread-Dongle IP", "required": True},
        "dongle_port": {"type": "number", "label": "Thread-Dongle Port", "default": 6638, "required": True},
        "otbr_url": {"type": "url", "label": "OTBR Dataset URL", "required": True},
    }

    REQUIRED = ("dongle_ip", "dongle_port", "otbr_url")

    def run(self):
        dongle_ip = self.check["dongle_ip"]
        dongle_port = int(self.check.get("dongle_port", 6638))
        otbr_url = self.check["otbr_url"]

        details = {"guardian": self.GUARDIAN}

        ping_result = ping(dongle_ip, self.timeout)
        details["ping"] = ping_result

        if not ping_result["ok"]:
            return self.result(
                "critical",
                2,
                "Thread-Dongle ist per Ping nicht erreichbar",
                int(ping_result["ms"]),
                details,
            )

        tcp_result = tcp_check(dongle_ip, dongle_port, self.timeout)
        details[f"tcp_{dongle_port}"] = tcp_result

        if not tcp_result["ok"]:
            return self.result(
                "critical",
                2,
                f"Thread-Dongle Port {dongle_port} ist nicht erreichbar",
                int(tcp_result["ms"]),
                details,
            )

        rest_result = get_json(otbr_url, self.timeout)
        details["otbr_rest"] = {
            "ok": rest_result["ok"],
            "ms": rest_result["ms"],
        }

        if not rest_result["ok"]:
            details["otbr_rest"]["error"] = rest_result.get("error")

            return self.result(
                "critical",
                2,
                "OTBR REST liefert kein aktives Dataset",
                int(rest_result["ms"]),
                details,
            )

        dataset = rest_result["data"]

        details["dataset"] = {
            "network_name": dataset.get("networkName"),
            "channel": dataset.get("channel"),
            "pan_id": dataset.get("panId"),
            "ext_pan_id": dataset.get("extPanId"),
        }

        if not dataset.get("networkName"):
            return self.result(
                "warning",
                1,
                "OTBR REST antwortet, aber networkName fehlt",
                int(rest_result["ms"]),
                details,
            )

        return self.result(
            "ok",
            0,
            "Thread-Dongle und OTBR REST funktionieren",
            int(rest_result["ms"]),
            details,
        )
