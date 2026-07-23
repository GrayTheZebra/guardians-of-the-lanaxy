import json
import socket
import time
from http.client import HTTPConnection
from urllib.parse import quote

import requests

from guardians.base import BaseGuardian


class UnixSocketHTTPConnection(HTTPConnection):
    def __init__(self, socket_path, timeout=5):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "docker_container",
        "name": "Docker Container Guardian",
        "version": "1.1.0",
        "description": "Prüft Docker Engine, Containerstatus, Healthcheck und Neustarts",
        "icon": "box",
        "category": "Container",
        "service_family": "docker",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "mode": {
            "type": "select", "label": "Prüfmodus", "default": "container",
            "options": [
                {"value": "engine", "label": "Nur Docker Engine"},
                {"value": "container", "label": "Bestimmten Container prüfen"},
            ],
        },
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True, "hint": "Der MiniGuard muss online sein und diesen Check unterstützen."},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "connection": {
            "type": "select", "label": "Verbindung", "default": "unix",
            "options": [
                {"value": "unix", "label": "Lokaler Unix-Socket"},
                {"value": "http", "label": "Docker API über HTTP/HTTPS"},
            ],
        },
        "socket_path": {
            "type": "text", "label": "Docker-Socket", "default": "/var/run/docker.sock",
            "visible_if": {"field": "connection", "equals": "unix"},
            "hint": "Der Benutzer lanlord benötigt Leserechte auf den Docker-Socket.",
        },
        "api_url": {
            "type": "url", "label": "Docker API URL", "default": "http://127.0.0.1:2375",
            "visible_if": {"field": "connection", "equals": "http"},
        },
        "verify_tls": {
            "type": "checkbox", "label": "TLS-Zertifikat validieren", "default": True,
            "visible_if": {"field": "connection", "equals": "http"},
        },
        "container": {
            "type": "text", "label": "Containername oder ID",
            "visible_if": {"field": "mode", "equals": "container"},
        },
        "expected_state": {
            "type": "select", "label": "Erwarteter Zustand", "default": "running",
            "visible_if": {"field": "mode", "equals": "container"},
            "options": [
                {"value": "running", "label": "Läuft"},
                {"value": "stopped", "label": "Gestoppt"},
                {"value": "any", "label": "Beliebig, Container muss nur existieren"},
            ],
        },
        "require_healthy": {
            "type": "checkbox", "label": "Docker-Healthcheck muss healthy sein", "default": True,
            "visible_if": {"field": "mode", "equals": "container"},
            "hint": "Wird nur ausgewertet, wenn der Container einen Docker-Healthcheck besitzt.",
        },
        "warning_restart_count": {
            "type": "number", "label": "Warning ab Neustarts", "default": 3, "min": 0,
            "visible_if": {"field": "mode", "equals": "container"},
        },
        "critical_restart_count": {
            "type": "number", "label": "Critical ab Neustarts", "default": 10, "min": 0,
            "visible_if": {"field": "mode", "equals": "container"},
        },
        "minimum_uptime_minutes": {
            "type": "number", "label": "Mindestlaufzeit (Minuten)", "default": 0, "min": 0,
            "visible_if": {"field": "mode", "equals": "container"},
        },
    }

    @classmethod
    def validate_config(cls, check):
        super().validate_config(check)
        if check.get("mode", "container") == "container" and not str(check.get("container", "")).strip():
            raise ValueError("Für den Container-Modus ist ein Containername oder eine ID erforderlich.")
        if check.get("connection", "unix") == "unix" and not str(check.get("socket_path", "")).strip():
            raise ValueError("Der Docker-Socket darf nicht leer sein.")

    def _unix_json(self, path):
        connection = UnixSocketHTTPConnection(str(self.check.get("socket_path", "/var/run/docker.sock")), self.timeout)
        try:
            connection.request("GET", path, headers={"Host": "localhost"})
            response = connection.getresponse()
            body = response.read()
            if response.status >= 400:
                message = body.decode("utf-8", errors="replace")
                try:
                    message = json.loads(message).get("message", message)
                except ValueError:
                    pass
                raise RuntimeError(f"Docker API {response.status}: {message}")
            return json.loads(body.decode("utf-8"))
        finally:
            connection.close()

    def _http_json(self, path):
        base = str(self.check.get("api_url", "http://127.0.0.1:2375")).rstrip("/")
        response = requests.get(base + path, timeout=self.timeout, verify=bool(self.check.get("verify_tls", True)))
        if response.status_code >= 400:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise RuntimeError(f"Docker API {response.status_code}: {message}")
        return response.json()

    def _get_json(self, path):
        if self.check.get("connection", "unix") == "unix":
            return self._unix_json(path)
        return self._http_json(path)

    @staticmethod
    def _parse_started(value):
        if not value or str(value).startswith("0001-"):
            return None
        from datetime import datetime, timezone
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
        except ValueError:
            # Docker may return nanoseconds beyond Python's accepted precision.
            if "." in text:
                prefix, suffix = text.split(".", 1)
                timezone_part = "+00:00" if suffix.endswith("+00:00") else ""
                fraction = suffix.split("+", 1)[0][:6]
                return datetime.fromisoformat(f"{prefix}.{fraction}{timezone_part}").astimezone(timezone.utc).timestamp()
            raise

    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("docker")
        started = time.monotonic()
        details = {"guardian": self.GUARDIAN, "connection": self.check.get("connection", "unix"), "mode": self.check.get("mode", "container")}
        try:
            version = self._get_json("/version")
            details.update({
                "docker_version": version.get("Version"),
                "api_version": version.get("ApiVersion"),
                "os": version.get("Os"),
                "architecture": version.get("Arch"),
            })
            if self.check.get("mode", "container") == "engine":
                ms = int((time.monotonic() - started) * 1000)
                return self.ok(f"{self.name}: Docker Engine {version.get('Version', 'erreichbar')} ist erreichbar", ms, details)

            identifier = quote(str(self.check["container"]).strip(), safe="")
            data = self._get_json(f"/containers/{identifier}/json")
        except (OSError, requests.RequestException, RuntimeError, ValueError, json.JSONDecodeError) as error:
            ms = int((time.monotonic() - started) * 1000)
            details["error"] = str(error)
            return self.critical(f"{self.name}: Docker-Prüfung fehlgeschlagen: {error}", ms, details)

        state = data.get("State") or {}
        config = data.get("Config") or {}
        container_name = str(data.get("Name") or self.check.get("container", "")).lstrip("/")
        status = str(state.get("Status", "unknown"))
        running = bool(state.get("Running"))
        restart_count = int(data.get("RestartCount") or 0)
        health = (state.get("Health") or {}).get("Status")
        started_at = self._parse_started(state.get("StartedAt"))
        uptime = max(0, time.time() - started_at) if started_at and running else 0
        details.update({
            "container": container_name,
            "container_id": str(data.get("Id", ""))[:12],
            "image": config.get("Image"),
            "status": status,
            "running": running,
            "health": health,
            "restart_count": restart_count,
            "started_at": state.get("StartedAt"),
            "uptime_seconds": round(uptime),
            "exit_code": state.get("ExitCode"),
            "error": state.get("Error") or None,
        })
        ms = int((time.monotonic() - started) * 1000)
        expected = self.check.get("expected_state", "running")
        if expected == "running" and not running:
            return self.critical(f"{self.name}: Container {container_name} läuft nicht ({status})", ms, details)
        if expected == "stopped" and running:
            return self.critical(f"{self.name}: Container {container_name} läuft, erwartet wird gestoppt", ms, details)
        if bool(self.check.get("require_healthy", True)) and health and health != "healthy":
            return self.critical(f"{self.name}: Container {container_name} ist {health}", ms, details)

        minimum = float(self.check.get("minimum_uptime_minutes", 0) or 0) * 60
        if minimum and running and uptime < minimum:
            return self.warning(f"{self.name}: Container {container_name} läuft erst seit {uptime / 60:.1f} Minuten", ms, details)

        critical_restarts = int(self.check.get("critical_restart_count", 0) or 0)
        warning_restarts = int(self.check.get("warning_restart_count", 0) or 0)
        if critical_restarts and restart_count >= critical_restarts:
            return self.critical(f"{self.name}: Container {container_name} wurde {restart_count}-mal neu gestartet", ms, details)
        if warning_restarts and restart_count >= warning_restarts:
            return self.warning(f"{self.name}: Container {container_name} wurde {restart_count}-mal neu gestartet", ms, details)

        health_text = f", Health {health}" if health else ""
        return self.ok(f"{self.name}: Container {container_name} ist {status}{health_text}", ms, details)
