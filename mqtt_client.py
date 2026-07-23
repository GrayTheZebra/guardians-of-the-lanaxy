import json
import threading
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt


class MqttPublisher:
    def __init__(self, config: dict | None = None):
        config = config or {}
        self.enabled = bool(config.get("enabled", False))
        self.host = str(config.get("host", "")).strip()
        self.port = int(config.get("port", 1883))
        self.user = config.get("user")
        self.password = config.get("password")
        self.base_topic = config.get("base_topic", "lanaxy").rstrip("/")
        self.retain = bool(config.get("retain", True))
        self.keepalive = int(config.get("keepalive", 60))
        self.homeassistant_discovery = bool(config.get("homeassistant_discovery", True))
        self.discovery_prefix = str(config.get("discovery_prefix", "homeassistant")).strip("/") or "homeassistant"

        self.connected = threading.Event()
        self.last_connect_error: str | None = None

        self.client = None
        if self.enabled:
            self.client = mqtt.Client()
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect

            if self.user:
                self.client.username_pw_set(self.user, self.password)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.last_connect_error = None
            self.connected.set()
            if self.homeassistant_discovery:
                try:
                    self.publish_homeassistant_discovery()
                except Exception as error:
                    self.last_connect_error = f"Home-Assistant-Discovery fehlgeschlagen: {error}"
        else:
            self.last_connect_error = f"MQTT Return Code {rc}"
            self.connected.clear()

    def _on_disconnect(self, client, userdata, rc):
        self.connected.clear()

    def connect(self, timeout: int = 10):
        if not self.enabled:
            self.connected.clear()
            self.last_connect_error = None
            return
        if not self.host:
            raise ValueError("MQTT ist aktiviert, aber es wurde kein Host eingetragen.")
        assert self.client is not None
        self.client.connect(self.host, self.port, self.keepalive)
        self.client.loop_start()

        if not self.connected.wait(timeout):
            raise ConnectionError(
                self.last_connect_error
                or f"MQTT-Verbindung zu {self.host}:{self.port} fehlgeschlagen"
            )

    def disconnect(self):
        if not self.enabled:
            return
        assert self.client is not None
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    @staticmethod
    def _serialize(payload: Any) -> str:
        if isinstance(payload, bool):
            return "true" if payload else "false"
        if payload is None:
            return ""
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False)
        return str(payload)

    def publish(self, topic: str, payload: Any):
        if not self.enabled:
            return
        assert self.client is not None
        info = self.client.publish(
            topic,
            self._serialize(payload),
            retain=self.retain,
        )

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(
                f"MQTT Publish auf {topic} fehlgeschlagen: RC {info.rc}"
            )

    def publish_result(self, result):
        data = result.to_dict()
        topic_base = f"{self.base_topic}/{result.id}"

        for key, value in data.items():
            self.publish(f"{topic_base}/{key}", value)

        self.publish(f"{topic_base}/json", data)


    def publish_homeassistant_discovery(self):
        """Publish retained Home Assistant MQTT Discovery entities for LANaxy."""
        device_id = "lanaxy_system"
        state_topic = f"{self.base_topic}/system/json"
        availability_topic = f"{self.base_topic}/system/heartbeat"
        device = {
            "identifiers": [device_id],
            "name": "Guardians of the LANaxy",
            "manufacturer": "LANaxy",
            "model": "System MQTT",
        }
        entities = {
            f"{self.discovery_prefix}/sensor/{device_id}_status/config": {
                "name": "Status", "unique_id": f"{device_id}_status",
                "state_topic": state_topic, "value_template": "{{ value_json.status }}",
                "icon": "mdi:shield-check", "device": device,
            },
            f"{self.discovery_prefix}/sensor/{device_id}_problems/config": {
                "name": "Probleme", "unique_id": f"{device_id}_problems",
                "state_topic": state_topic, "value_template": "{{ value_json.errors }}",
                "icon": "mdi:alert-circle-outline", "device": device,
            },
            f"{self.discovery_prefix}/sensor/{device_id}_last_update/config": {
                "name": "Letzte Aktualisierung", "unique_id": f"{device_id}_last_update",
                "state_topic": state_topic, "value_template": "{{ value_json.last_update }}",
                "device_class": "timestamp", "icon": "mdi:update", "device": device,
            },
            f"{self.discovery_prefix}/binary_sensor/{device_id}_problem/config": {
                "name": "Störung", "unique_id": f"{device_id}_problem",
                "state_topic": state_topic,
                "value_template": "{{ 'ON' if value_json.level | int > 0 else 'OFF' }}",
                "payload_on": "ON", "payload_off": "OFF", "device_class": "problem",
                "device": device,
            },
        }
        for topic, payload in entities.items():
            info = self.client.publish(topic, json.dumps(payload, ensure_ascii=False), retain=True)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError(f"Discovery Publish auf {topic} fehlgeschlagen: RC {info.rc}")

    def publish_system(self, results):
        worst_level = max((result.level for result in results), default=0)

        if worst_level == 2:
            status = "critical"
        elif worst_level == 1:
            status = "warning"
        else:
            status = "ok"

        errors = sum(1 for result in results if result.level > 0)

        data = {
            "status": status,
            "level": worst_level,
            "errors": errors,
            "message": (
                "Alle Guardians OK"
                if errors == 0
                else f"{errors} Problem(e) erkannt"
            ),
            "last_update": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

        topic_base = f"{self.base_topic}/system"

        for key, value in data.items():
            self.publish(f"{topic_base}/{key}", value)

        self.publish(f"{topic_base}/json", data)

    def publish_heartbeat(self):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        self.publish(f"{self.base_topic}/system/heartbeat", now)

    def publish_info(self, info: dict):
        topic_base = f"{self.base_topic}/system/info"

        for key, value in info.items():
            self.publish(f"{topic_base}/{key}", value)

        self.publish(f"{topic_base}/json", info)

    def publish_guardians(self, guardians: list):
        self.publish(f"{self.base_topic}/system/guardians", guardians)

    def publish_event(self, event):
        data = event.to_dict()
        event_type = data.get("type", "event").lower()
        source = data.get("source", "unknown")

        topic_base = f"{self.base_topic}/events/{source}/{event_type}"

        self.publish(f"{topic_base}/json", data)
        self.publish(f"{self.base_topic}/events/last/json", data)
        self.publish(
            f"{self.base_topic}/events/last/message",
            data.get("message", ""),
        )
        self.publish(
            f"{self.base_topic}/events/last/type",
            data.get("type", ""),
        )
        self.publish(f"{self.base_topic}/events/last/source", source)
