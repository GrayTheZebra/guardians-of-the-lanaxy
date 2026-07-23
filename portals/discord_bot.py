import threading

import requests

from control_portal_utils import allowed, format_result, parse_chat_command
from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "discord_bot",
        "name": "Discord Bot",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Steuert LANaxy über Textbefehle in ausgewählten Discord-Kanälen.",
        "icon": "discord",
        "category": "Chat",
    }
    CONFIG_SCHEMA = {
        "name": {"label": "Name", "type": "text", "required": True},
        "bot_token": {"label": "Bot-Token", "type": "password", "secret": True, "required": True},
        "channel_ids": {
            "label": "Erlaubte Kanal-IDs",
            "type": "text",
            "required": True,
            "help": "Kommagetrennte Discord-Kanal-IDs, die in kurzen Abständen abgefragt werden.",
        },
        "allowed_user_ids": {
            "label": "Erlaubte Benutzer-IDs",
            "type": "text",
            "help": "Optional, kommagetrennte Benutzer-IDs. Leer erlaubt alle Benutzer der ausgewählten Kanäle.",
        },
        "command_prefix": {"label": "Befehlspräfix", "type": "text", "default": "!lanaxy"},
        "poll_interval": {"label": "Abfrageintervall in Sekunden", "type": "number", "default": 5},
        "allowed_commands": {"label": "Erlaubte Befehle", "type": "command_checkboxes", "default": "*"},
    }
    REQUIRED = ("name", "bot_token", "channel_ids", "command_prefix")
    BACKGROUND = True

    API = "https://discord.com/api/v10"

    def __init__(self, config, command_handler, token_validator):
        super().__init__(config, command_handler, token_validator)
        self._stop = threading.Event()
        self._thread = None
        self._last_ids = {}
        self._bot_id = ""

    @property
    def headers(self):
        return {"Authorization": f"Bot {self.config['bot_token']}", "Content-Type": "application/json"}

    def _ids(self, key):
        return {x.strip() for x in str(self.config.get(key, "")).split(",") if x.strip()}

    def _send(self, channel_id, text):
        requests.post(f"{self.API}/channels/{channel_id}/messages", headers=self.headers, json={"content": text[:1900]}, timeout=15).raise_for_status()

    def _poll_channel(self, channel_id):
        params = {"limit": 20}
        if self._last_ids.get(channel_id):
            params["after"] = self._last_ids[channel_id]
        response = requests.get(f"{self.API}/channels/{channel_id}/messages", headers=self.headers, params=params, timeout=15)
        response.raise_for_status()
        messages = sorted(response.json(), key=lambda item: int(item["id"]))
        if channel_id not in self._last_ids:
            self._last_ids[channel_id] = messages[-1]["id"] if messages else "0"
            return
        for message in messages:
            self._last_ids[channel_id] = message["id"]
            author = message.get("author") or {}
            if str(author.get("id", "")) == self._bot_id or author.get("bot"):
                continue
            users = self._ids("allowed_user_ids")
            if users and str(author.get("id", "")) not in users:
                continue
            prefix = str(self.config.get("command_prefix", "!lanaxy")).strip()
            content = str(message.get("content", "")).strip()
            if not content.lower().startswith(prefix.lower()):
                continue
            command_text = content[len(prefix):].strip()
            if command_text and not command_text.startswith("/"):
                command_text = "/" + command_text
            payload, reply = parse_chat_command(command_text or "/help")
            if reply:
                self._send(channel_id, reply)
            elif payload:
                if not allowed(self.config, payload.get("command", "")):
                    self._send(channel_id, "Dieser Befehl ist für das Portal nicht freigegeben.")
                else:
                    result = self.command_handler(payload, f"discord:{self.config.get('id', 'portal')}:{channel_id}")
                    self._send(channel_id, format_result(result))

    def _run(self):
        self.running = True
        try:
            response = requests.get(f"{self.API}/users/@me", headers=self.headers, timeout=15)
            response.raise_for_status()
            self._bot_id = str(response.json().get("id", ""))
        except Exception as error:
            self.last_error = str(error)
            self.running = False
        while not self._stop.is_set():
            try:
                for channel_id in self._ids("channel_ids"):
                    self._poll_channel(channel_id)
                self.last_error = ""
            except Exception as error:
                self.last_error = str(error)
            self._stop.wait(max(2, int(self.config.get("poll_interval", 5))))
        self.running = False

    def start(self):
        self.validate_config(self.config)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"lanaxy-discord-{self.config.get('id')}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.running = False

    def test(self):
        try:
            response = requests.get(f"{self.API}/users/@me", headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            return {"running": self.running, "last_error": "", "message": f"Bot {data.get('username', '?')} erreichbar."}
        except Exception as error:
            self.last_error = str(error)
            return {"running": False, "last_error": self.last_error}
