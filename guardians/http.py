import json
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "http",
        "name": "HTTP/HTTPS Guardian",
        "version": "1.0.0",
        "description": "Prüft URLs, Statuscodes, Inhalte, Antwortzeiten und TLS-Zertifikate",
        "icon": "globe",
        "category": "Netzwerk",
        "service_family": "http",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 5},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 10, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "url": {"type": "url", "label": "URL", "required": True},
        "method": {
            "type": "select", "label": "HTTP-Methode", "default": "GET",
            "options": [
                {"value": "GET", "label": "GET"},
                {"value": "HEAD", "label": "HEAD"},
            ],
        },
        "expected_status": {"type": "text", "label": "Erwartete Statuscodes", "default": "200", "help": "Zum Beispiel 200, 204 oder 200-299"},
        "follow_redirects": {"type": "checkbox", "label": "Redirects folgen", "default": True},
        "verify_tls": {"type": "checkbox", "label": "TLS-Zertifikat validieren", "default": True},
        "certificate_warning_days": {"type": "number", "label": "Zertifikatswarnung (Tage)", "default": 30, "min": 0},
        "warning_response_ms": {"type": "number", "label": "Warnung ab Antwortzeit (ms)", "default": 1000, "min": 0},
        "critical_response_ms": {"type": "number", "label": "Critical ab Antwortzeit (ms)", "default": 5000, "min": 0},
        "headers": {"type": "textarea", "label": "Eigene Header", "help": "Ein Header pro Zeile: Name: Wert"},
        "bearer_token": {"type": "password", "label": "Bearer-Token", "secret": True},
        "text_contains": {"type": "text", "label": "Antwort muss Text enthalten"},
        "json_path": {"type": "text", "label": "JSON-Pfad", "help": "Punktnotation, zum Beispiel status.health"},
        "json_expected": {"type": "text", "label": "Erwarteter JSON-Wert"},
    }

    REQUIRED = ("url",)

    @staticmethod
    def _parse_headers(raw):
        if not raw:
            return {}
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        headers = {}
        for line in str(raw).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"Ungültiger HTTP-Header: {line}")
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
        return headers

    @staticmethod
    def _status_matches(status, specification):
        specification = str(specification or "200").strip()
        for part in specification.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                if int(start) <= status <= int(end):
                    return True
            elif status == int(part):
                return True
        return False

    @staticmethod
    def _json_value(payload, path):
        value = payload
        for part in path.split("."):
            if isinstance(value, list):
                value = value[int(part)]
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                raise KeyError(path)
        return value

    @staticmethod
    def _expected_value(raw):
        if raw is None:
            return None
        try:
            return json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            return str(raw)

    @staticmethod
    def _certificate(url, timeout, verify_tls):
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            return None
        host = parsed.hostname
        port = parsed.port or 443
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                certificate = tls_socket.getpeercert()
                if not certificate:
                    return {"available": False}
                expires = datetime.strptime(
                    certificate["notAfter"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)
                remaining = expires - datetime.now(timezone.utc)
                return {
                    "available": True,
                    "expires_at": expires.isoformat(),
                    "days_remaining": max(0, int(remaining.total_seconds() // 86400)),
                    "subject": dict(item[0] for item in certificate.get("subject", [])),
                    "issuer": dict(item[0] for item in certificate.get("issuer", [])),
                }

    def run(self):
        url = str(self.check["url"]).strip()
        method = str(self.check.get("method", "GET")).upper()
        follow_redirects = bool(self.check.get("follow_redirects", True))
        verify_tls = bool(self.check.get("verify_tls", True))
        headers = self._parse_headers(self.check.get("headers"))
        token = self.check.get("bearer_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        details = {
            "guardian": self.GUARDIAN,
            "url": url,
            "method": method,
            "follow_redirects": follow_redirects,
            "tls_validation": verify_tls,
        }

        started = time.monotonic()
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=follow_redirects,
                verify=verify_tls,
            )
            response_ms = int((time.monotonic() - started) * 1000)
        except requests.exceptions.SSLError as error:
            details["error_type"] = "tls"
            details["error"] = str(error)
            return self.critical(f"{self.name}: TLS-Zertifikatsfehler", details=details)
        except requests.exceptions.Timeout as error:
            details["error_type"] = "timeout"
            details["error"] = str(error)
            return self.critical(f"{self.name}: HTTP-Timeout nach {self.timeout} Sekunden", int(self.timeout * 1000), details)
        except requests.exceptions.ConnectionError as error:
            details["error_type"] = "connection"
            details["error"] = str(error)
            return self.critical(f"{self.name}: Verbindung fehlgeschlagen", details=details)
        except requests.RequestException as error:
            details["error_type"] = "request"
            details["error"] = str(error)
            return self.critical(f"{self.name}: HTTP-Anfrage fehlgeschlagen", details=details)

        details.update({
            "status_code": response.status_code,
            "response_ms": response_ms,
            "final_url": response.url,
            "redirected": bool(response.history),
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": len(response.content),
        })

        if not follow_redirects and 300 <= response.status_code < 400:
            details["location"] = response.headers.get("Location")

        if not self._status_matches(response.status_code, self.check.get("expected_status", "200")):
            return self.critical(
                f"{self.name}: unerwarteter HTTP-Status {response.status_code}",
                response_ms,
                details,
            )

        text_contains = self.check.get("text_contains")
        if text_contains and str(text_contains) not in response.text:
            return self.critical(
                f"{self.name}: erwarteter Text wurde nicht gefunden",
                response_ms,
                details,
            )

        json_path = self.check.get("json_path")
        if json_path:
            try:
                payload = response.json()
                actual = self._json_value(payload, str(json_path))
            except (ValueError, KeyError, IndexError, TypeError) as error:
                details["json_error"] = str(error)
                return self.critical(
                    f"{self.name}: JSON-Pfad {json_path} konnte nicht geprüft werden",
                    response_ms,
                    details,
                )
            expected_raw = self.check.get("json_expected")
            details["json_path"] = json_path
            details["json_actual"] = actual
            if expected_raw is not None and str(expected_raw) != "":
                expected = self._expected_value(expected_raw)
                details["json_expected"] = expected
                if actual != expected and str(actual) != str(expected):
                    return self.critical(
                        f"{self.name}: JSON-Wert entspricht nicht der Erwartung",
                        response_ms,
                        details,
                    )

        certificate_warning = None
        if urlparse(url).scheme.lower() == "https":
            try:
                certificate = self._certificate(url, self.timeout, verify_tls)
                details["certificate"] = certificate
                warning_days = int(self.check.get("certificate_warning_days", 30))
                if certificate and certificate.get("available") and certificate["days_remaining"] <= warning_days:
                    certificate_warning = (
                        f"{self.name}: Zertifikat läuft in "
                        f"{certificate['days_remaining']} Tagen ab"
                    )
            except (OSError, ssl.SSLError, ValueError) as error:
                details["certificate_check_error"] = str(error)
                if verify_tls:
                    return self.critical(
                        f"{self.name}: Zertifikat konnte nicht geprüft werden",
                        response_ms,
                        details,
                    )

        critical_ms = int(self.check.get("critical_response_ms", 5000) or 0)
        warning_ms = int(self.check.get("warning_response_ms", 1000) or 0)
        if critical_ms and response_ms >= critical_ms:
            return self.critical(
                f"{self.name}: Antwortzeit kritisch ({response_ms} ms)",
                response_ms,
                details,
            )
        if certificate_warning:
            return self.warning(certificate_warning, response_ms, details)
        if warning_ms and response_ms >= warning_ms:
            return self.warning(
                f"{self.name}: Antwortzeit erhöht ({response_ms} ms)",
                response_ms,
                details,
            )

        return self.ok(
            f"{self.name}: HTTP {response.status_code} in {response_ms} ms",
            response_ms,
            details,
        )
