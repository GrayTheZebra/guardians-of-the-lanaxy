import json
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from guardians.base import BaseGuardian
from utils.network import ping, tcp_check


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "zigbee2mqtt",
        "name": "Zigbee2MQTT Guardian",
        "version": "1.0.0",
        "description": (
            "Überwacht Zigbee2MQTT, MQTT und lokale oder entfernte Coordinatoren"
        ),
        "icon": "zigbee",
        "category": "Smart Home",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 15, "min": 2},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "z2m_host": {"type": "text", "label": "Zigbee2MQTT Host/LXC", "required": True},
        "frontend_port": {"type": "number", "label": "Frontend-Port", "default": 8080, "required": True},
        "mqtt.host": {"type": "text", "label": "Zigbee2MQTT MQTT Host", "required": True},
        "mqtt.port": {"type": "number", "label": "Zigbee2MQTT MQTT Port", "default": 1883, "required": True},
        "mqtt.user": {"type": "text", "label": "Zigbee2MQTT MQTT Benutzer"},
        "mqtt.password": {"type": "password", "label": "Zigbee2MQTT MQTT Passwort", "secret": True},
        "mqtt.keepalive": {"type": "number", "label": "MQTT Keepalive", "default": 60},
        "mqtt.base_topic": {"type": "text", "label": "Zigbee2MQTT Base Topic", "default": "zigbee2mqtt", "required": True},
        "coordinator.type": {
            "type": "select",
            "label": "Coordinator-Typ",
            "required": True,
            "default": "usb",
            "options": [
                {"value": "usb", "label": "USB-Stick"},
                {"value": "tcp", "label": "TCP / PoE"},
            ],
        },
        "coordinator.host": {
            "type": "text",
            "label": "Coordinator Host/IP",
            "visible_if": {"field": "coordinator.type", "equals": "tcp"},
        },
        "coordinator.port": {
            "type": "number",
            "label": "Coordinator TCP-Port",
            "default": 6638,
            "visible_if": {"field": "coordinator.type", "equals": "tcp"},
        },
    }

    REQUIRED = ("z2m_host", "frontend_port", "mqtt", "coordinator")

    @classmethod
    def validate_config(cls, check: dict) -> None:
        super().validate_config(check)

        mqtt_config = check.get("mqtt")
        if not isinstance(mqtt_config, dict):
            raise ValueError("'mqtt' muss ein Konfigurationsblock sein.")

        for key in ("host", "port", "base_topic"):
            if key not in mqtt_config:
                raise ValueError(f"Zigbee2MQTT MQTT-Konfiguration fehlt: {key}")

        coordinator = check.get("coordinator")
        if not isinstance(coordinator, dict):
            raise ValueError("'coordinator' muss ein Konfigurationsblock sein.")

        coordinator_type = coordinator.get("type")
        if coordinator_type not in ("usb", "tcp"):
            raise ValueError("coordinator.type muss 'usb' oder 'tcp' sein.")

        if coordinator_type == "tcp":
            for key in ("host", "port"):
                if key not in coordinator:
                    raise ValueError(
                        f"TCP-Coordinator-Konfiguration fehlt: {key}"
                    )

    def _mqtt_health_check(
        self,
        mqtt_config: dict[str, Any],
    ) -> dict[str, Any]:
        host = mqtt_config["host"]
        port = int(mqtt_config.get("port", 1883))
        user = mqtt_config.get("user")
        password = mqtt_config.get("password")
        keepalive = int(mqtt_config.get("keepalive", 60))
        base_topic = str(mqtt_config["base_topic"]).rstrip("/")

        request_topic = f"{base_topic}/bridge/request/health_check"
        response_topic = f"{base_topic}/bridge/response/health_check"

        connected_event = threading.Event()
        response_event = threading.Event()

        state: dict[str, Any] = {
            "connect_rc": None,
            "payload": None,
            "error": None,
        }

        def on_connect(client, userdata, flags, rc):
            state["connect_rc"] = rc

            if rc != 0:
                state["error"] = f"MQTT Return Code {rc}"
                connected_event.set()
                response_event.set()
                return

            client.subscribe(response_topic)
            connected_event.set()

        def on_message(client, userdata, message):
            try:
                decoded = message.payload.decode("utf-8", errors="replace")
                state["payload"] = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                state["error"] = f"Ungültige Health-Check-Antwort: {error}"
            finally:
                response_event.set()

        started = time.monotonic()
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message

        if user:
            client.username_pw_set(user, password)

        try:
            client.connect(host, port, keepalive)
            client.loop_start()

            if not connected_event.wait(self.timeout):
                return {
                    "ok": False,
                    "phase": "mqtt_connect",
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": (
                        f"MQTT-Verbindung zu {host}:{port} "
                        "innerhalb des Timeouts fehlgeschlagen"
                    ),
                    "request_topic": request_topic,
                    "response_topic": response_topic,
                }

            if state["connect_rc"] != 0:
                return {
                    "ok": False,
                    "phase": "mqtt_auth",
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": state["error"],
                    "request_topic": request_topic,
                    "response_topic": response_topic,
                }

            publish_info = client.publish(request_topic, "{}")

            if publish_info.rc != mqtt.MQTT_ERR_SUCCESS:
                return {
                    "ok": False,
                    "phase": "mqtt_publish",
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": f"MQTT Publish Return Code {publish_info.rc}",
                    "request_topic": request_topic,
                    "response_topic": response_topic,
                }

            if not response_event.wait(self.timeout):
                return {
                    "ok": False,
                    "phase": "health_timeout",
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": (
                        "Zigbee2MQTT beantwortet den MQTT-Health-Check nicht"
                    ),
                    "request_topic": request_topic,
                    "response_topic": response_topic,
                }

            if state["error"]:
                return {
                    "ok": False,
                    "phase": "health_response",
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": state["error"],
                    "request_topic": request_topic,
                    "response_topic": response_topic,
                }

            payload = state["payload"]
            status = payload.get("status") if isinstance(payload, dict) else None
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            healthy = data.get("healthy") if isinstance(data, dict) else None

            is_healthy = status == "ok" and healthy is not False

            return {
                "ok": is_healthy,
                "phase": "health",
                "ms": int((time.monotonic() - started) * 1000),
                "status": status,
                "healthy": healthy,
                "payload": payload,
                "request_topic": request_topic,
                "response_topic": response_topic,
                "error": (
                    None
                    if is_healthy
                    else "Zigbee2MQTT meldet einen fehlerhaften Health-Status"
                ),
            }

        except Exception as error:
            return {
                "ok": False,
                "phase": "mqtt_connect",
                "ms": int((time.monotonic() - started) * 1000),
                "error": str(error),
                "request_topic": request_topic,
                "response_topic": response_topic,
            }
        finally:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:
                pass

    def run(self):
        z2m_host = self.check["z2m_host"]
        frontend_port = int(self.check["frontend_port"])
        mqtt_config = self.check["mqtt"]
        coordinator = self.check["coordinator"]
        coordinator_type = coordinator["type"]

        details: dict[str, Any] = {
            "guardian": self.GUARDIAN,
            "z2m_host": z2m_host,
            "frontend_port": frontend_port,
            "coordinator": coordinator,
        }

        z2m_ping = ping(z2m_host, self.timeout)
        details["z2m_ping"] = z2m_ping

        if not z2m_ping["ok"]:
            return self.result(
                "critical",
                2,
                "Zigbee2MQTT-LXC ist nicht erreichbar",
                int(z2m_ping["ms"]),
                details,
            )

        if coordinator_type == "tcp":
            coordinator_host = coordinator["host"]
            coordinator_port = int(coordinator["port"])

            coordinator_ping = ping(coordinator_host, self.timeout)
            details["coordinator_ping"] = coordinator_ping

            if not coordinator_ping["ok"]:
                return self.result(
                    "critical",
                    2,
                    "Zigbee-PoE-Dongle ist nicht erreichbar",
                    int(coordinator_ping["ms"]),
                    details,
                )

            coordinator_tcp = tcp_check(
                coordinator_host,
                coordinator_port,
                self.timeout,
            )
            details["coordinator_tcp"] = coordinator_tcp

            if not coordinator_tcp["ok"]:
                return self.result(
                    "critical",
                    2,
                    (
                        "Zigbee-PoE-Dongle ist erreichbar, "
                        f"antwortet aber nicht auf Port {coordinator_port}"
                    ),
                    int(coordinator_tcp["ms"]),
                    details,
                )

        frontend_check = tcp_check(
            z2m_host,
            frontend_port,
            self.timeout,
        )
        details["frontend"] = frontend_check

        if not frontend_check["ok"]:
            return self.result(
                "critical",
                2,
                (
                    "Zigbee2MQTT-LXC ist erreichbar, "
                    f"aber der Dienst antwortet nicht auf Port {frontend_port}"
                ),
                int(frontend_check["ms"]),
                details,
            )

        health = self._mqtt_health_check(mqtt_config)
        details["health_check"] = health

        if not health["ok"]:
            phase = health.get("phase")

            if phase in ("mqtt_connect", "mqtt_auth", "mqtt_publish"):
                message = (
                    "MQTT-Broker für Zigbee2MQTT ist nicht erreichbar "
                    "oder lehnt die Verbindung ab"
                )
            elif phase == "health_timeout":
                if coordinator_type == "usb":
                    message = (
                        "Zigbee2MQTT läuft, beantwortet den Health-Check aber "
                        "nicht; der USB-Coordinator ist möglicherweise nicht "
                        "verfügbar oder Zigbee2MQTT hängt"
                    )
                else:
                    message = (
                        "Zigbee2MQTT läuft, beantwortet den Health-Check aber "
                        "nicht; der Dienst oder Coordinator reagiert nicht"
                    )
            else:
                if coordinator_type == "usb":
                    message = (
                        "Zigbee2MQTT meldet einen Fehler; der USB-Coordinator "
                        "ist möglicherweise nicht verfügbar"
                    )
                else:
                    message = (
                        "Zigbee2MQTT meldet einen Fehler beim Dienst oder "
                        "Coordinator"
                    )

            return self.result(
                "critical",
                2,
                message,
                int(health["ms"]),
                details,
            )

        if coordinator_type == "usb":
            message = (
                "Zigbee2MQTT, MQTT und USB-Coordinator funktionieren"
            )
        else:
            message = (
                "Zigbee2MQTT, MQTT und PoE-Coordinator funktionieren"
            )

        return self.result(
            "ok",
            0,
            message,
            int(health["ms"]),
            details,
        )
