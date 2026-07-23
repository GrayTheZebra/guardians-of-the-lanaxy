from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "http",
        "name": "HTTP API",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Empfängt Control-Befehle per HTTP REST API.",
        "icon": "webhook",
        "category": "Automation",
    }
    CONFIG_SCHEMA = {
        "name": {
            "label": "Name",
            "type": "text",
            "required": True,
        },
        "allowed_commands": {
            "label": "Erlaubte Befehle",
            "type": "command_checkboxes",
            "default": "*",
            "help": "Kommagetrennt oder * für alle Runtime-Befehle.",
        },
        "ip_allowlist": {
            "label": "IP-Allowlist",
            "type": "text",
            "help": "Optional, kommagetrennte IP-Adressen.",
        },
        "rate_limit_per_minute": {
            "label": "Maximale Anfragen pro Minute",
            "type": "number",
            "default": 60,
        },
    }
    REQUIRED = ("name",)
    BACKGROUND = False
