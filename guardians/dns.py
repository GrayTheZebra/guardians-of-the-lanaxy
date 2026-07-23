import socket
import time

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "dns", "name": "DNS Guardian", "version": "1.0.0",
        "description": "Prüft DNS-Auflösung, erwartete Adressen und Antwortzeit",
        "icon": "globe", "category": "Netzwerk", "service_family": "dns",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "hostname": {"type": "text", "label": "Hostname", "required": True},
        "record_type": {"type": "select", "label": "Record-Typ", "default": "A", "options": [{"value":"A","label":"A (IPv4)"},{"value":"AAAA","label":"AAAA (IPv6)"}]},
        "expected_value": {"type": "text", "label": "Erwartete Adresse", "hint": "Optional; mehrere Werte kommasepariert"},
        "warning_ms": {"type": "number", "label": "Warning ab Antwortzeit (ms)", "default": 500, "min": 0},
        "critical_ms": {"type": "number", "label": "Critical ab Antwortzeit (ms)", "default": 2000, "min": 0},
    }
    REQUIRED = ("hostname",)

    def run(self):
        started = time.monotonic()
        host = str(self.check["hostname"]).strip()
        rtype = str(self.check.get("record_type", "A")).upper()
        family = socket.AF_INET6 if rtype == "AAAA" else socket.AF_INET
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout)
        details = {"guardian": self.GUARDIAN, "hostname": host, "record_type": rtype}
        try:
            infos = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
            addresses = sorted({info[4][0] for info in infos})
        except socket.gaierror as error:
            details["error"] = str(error)
            return self.critical(f"{self.name}: DNS-Auflösung fehlgeschlagen: {error}", details=details)
        finally:
            socket.setdefaulttimeout(old_timeout)
        ms = int((time.monotonic() - started) * 1000)
        details.update(addresses=addresses, response_time_ms=ms)
        expected = {v.strip() for v in str(self.check.get("expected_value", "")).split(",") if v.strip()}
        if expected and not expected.intersection(addresses):
            return self.critical(f"{self.name}: Erwartete Adresse nicht gefunden; erhalten: {', '.join(addresses)}", ms, details)
        critical = int(self.check.get("critical_ms", 2000) or 0)
        warning = int(self.check.get("warning_ms", 500) or 0)
        if critical and ms >= critical:
            return self.critical(f"{self.name}: DNS-Antwort dauerte {ms} ms", ms, details)
        if warning and ms >= warning:
            return self.warning(f"{self.name}: DNS-Antwort dauerte {ms} ms", ms, details)
        return self.ok(f"{self.name}: {host} → {', '.join(addresses)} ({ms} ms)", ms, details)
