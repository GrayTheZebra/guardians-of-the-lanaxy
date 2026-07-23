import json
import threading

import paho.mqtt.client as mqtt

from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "mqtt",
        "name": "MQTT",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Empfängt Control-Befehle über MQTT und antwortet auf einem Result-Topic.",
        "icon": "mqtt",
        "category": "Automation",
    }
    CONFIG_SCHEMA = {
        "name": {"label": "Name", "type": "text", "required": True},
        "host": {"label": "Host oder IP", "type": "text", "required": True},
        "port": {"label": "Port", "type": "number", "default": 1883},
        "username": {"label": "Benutzername", "type": "text"},
        "password": {
            "label": "Passwort",
            "type": "password",
            "secret": True,
        },
        "command_topic": {
            "label": "Command Topic",
            "type": "text",
            "default": "lanaxy/control/command",
            "required": True,
        },
        "result_topic": {
            "label": "Result Topic",
            "type": "text",
            "default": "lanaxy/control/result",
            "required": True,
        },
        "client_id": {
            "label": "Client-ID",
            "type": "text",
            "default": "lanaxy-control",
        },
        "keepalive": {
            "label": "Keepalive",
            "type": "number",
            "default": 60,
        },
        "tls": {
            "label": "TLS verwenden",
            "type": "checkbox",
            "default": False,
        },
        "allowed_commands": {
            "label": "Erlaubte Befehle",
            "type": "command_checkboxes",
            "default": "*",
        },
    }
    REQUIRED = ("host", "command_topic", "result_topic")
    BACKGROUND = True

    def __init__(self, config, command_handler, token_validator):
        super().__init__(config, command_handler, token_validator)
        self.client = None
        self.connected = threading.Event()

    def _allowed(self, command):
        configured = str(
            self.config.get("allowed_commands", "*")
        ).strip()
        if configured == "*":
            return True
        return command in {
            item.strip()
            for item in configured.split(",")
            if item.strip()
        }

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(self.config["command_topic"])
            self.connected.set()
            self.running = True
            self.last_error = ""
        else:
            self.last_error = f"MQTT Return Code {rc}"

    def _on_disconnect(self, client, userdata, rc):
        self.connected.clear()
        self.running = False

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(
                message.payload.decode("utf-8")
            )
            token = str(payload.pop("token", ""))
            if not self.token_validator(token):
                result = {
                    "ok": False,
                    "error": "Ungültiger Control-Token.",
                    "request_id": payload.get("request_id", ""),
                }
            elif not self._allowed(payload.get("command")):
                result = {
                    "ok": False,
                    "error": "Befehl ist für dieses Portal nicht erlaubt.",
                    "request_id": payload.get("request_id", ""),
                }
            else:
                result = self.command_handler(
                    payload,
                    f"mqtt:{self.config.get('id', 'portal')}",
                )
        except Exception as error:
            result = {"ok": False, "error": str(error)}

        client.publish(
            self.config["result_topic"],
            json.dumps(result, ensure_ascii=False),
            qos=1,
            retain=False,
        )

    def start(self):
        self.validate_config(self.config)
        client = mqtt.Client(
            client_id=self.config.get("client_id", "")
        )
        if self.config.get("username"):
            client.username_pw_set(
                self.config.get("username"),
                self.config.get("password"),
            )
        if self.config.get("tls"):
            client.tls_set()
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(
            self.config["host"],
            int(self.config.get("port", 1883)),
            int(self.config.get("keepalive", 60)),
        )
        client.loop_start()
        self.client = client

    def stop(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()
        self.running = False

    def test(self):
        if self.client is None:
            return {
                "running": False,
                "last_error": self.last_error or "Nicht gestartet",
            }
        return self.health()
