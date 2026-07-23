import threading

import requests

from control_portal_utils import allowed, format_result, parse_chat_command
from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "telegram_bot",
        "name": "Telegram Bot",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Steuert LANaxy über Befehle an einen Telegram-Bot.",
        "icon": "telegram",
        "category": "Chat",
    }
    CONFIG_SCHEMA = {
        "name": {"label": "Name", "type": "text", "required": True},
        "bot_token": {"label": "Bot-Token", "type": "password", "secret": True, "required": True},
        "allowed_chat_ids": {
            "label": "Erlaubte Chat-IDs",
            "type": "text",
            "required": True,
            "help": "Kommagetrennte Telegram-Chat-IDs. Nachrichten anderer Chats werden ignoriert.",
        },
        "allowed_commands": {"label": "Erlaubte Befehle", "type": "command_checkboxes", "default": "*"},
        "poll_timeout": {"label": "Long-Polling-Timeout", "type": "number", "default": 25},
    }
    REQUIRED = ("name", "bot_token", "allowed_chat_ids")
    BACKGROUND = True

    def __init__(self, config, command_handler, token_validator):
        super().__init__(config, command_handler, token_validator)
        self._stop = threading.Event()
        self._thread = None
        self._offset = 0

    @property
    def api(self):
        return f"https://api.telegram.org/bot{self.config['bot_token']}"

    def _chat_ids(self):
        return {x.strip() for x in str(self.config.get("allowed_chat_ids", "")).split(",") if x.strip()}

    def _send(self, chat_id, text):
        requests.post(f"{self.api}/sendMessage", json={"chat_id": chat_id, "text": text[:4000]}, timeout=15).raise_for_status()

    def _run(self):
        self.running = True
        try:
            pending = requests.get(f"{self.api}/getUpdates", params={"offset": -1, "timeout": 0}, timeout=15).json().get("result", [])
            if pending:
                self._offset = int(pending[-1].get("update_id", 0)) + 1
        except Exception as error:
            self.last_error = str(error)
        while not self._stop.is_set():
            try:
                response = requests.get(
                    f"{self.api}/getUpdates",
                    params={"offset": self._offset, "timeout": int(self.config.get("poll_timeout", 25)), "allowed_updates": '["message"]'},
                    timeout=int(self.config.get("poll_timeout", 25)) + 10,
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description", "Telegram API meldet einen Fehler."))
                for update in data.get("result", []):
                    self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                    message = update.get("message") or {}
                    chat_id = str((message.get("chat") or {}).get("id", ""))
                    text = str(message.get("text", ""))
                    if not chat_id or chat_id not in self._chat_ids() or not text.startswith("/"):
                        continue
                    payload, reply = parse_chat_command(text)
                    if reply:
                        self._send(chat_id, reply)
                    elif payload:
                        if not allowed(self.config, payload.get("command", "")):
                            self._send(chat_id, "Dieser Befehl ist für das Portal nicht freigegeben.")
                        else:
                            result = self.command_handler(payload, f"telegram:{self.config.get('id', 'portal')}:{chat_id}")
                            self._send(chat_id, format_result(result))
                self.last_error = ""
            except Exception as error:
                self.last_error = str(error)
                self.running = False
                self._stop.wait(5)
                if not self._stop.is_set():
                    self.running = True
        self.running = False

    def start(self):
        self.validate_config(self.config)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"lanaxy-telegram-{self.config.get('id')}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.running = False

    def test(self):
        try:
            response = requests.get(f"{self.api}/getMe", timeout=15)
            response.raise_for_status()
            data = response.json().get("result", {})
            return {"running": self.running, "last_error": "", "message": f"Bot @{data.get('username', '?')} erreichbar."}
        except Exception as error:
            self.last_error = str(error)
            return {"running": False, "last_error": self.last_error}
