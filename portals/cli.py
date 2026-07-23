from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "cli",
        "name": "CLI",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Steuert LANaxy aus Shell-Skripten über einen eigenen Zugriffstoken.",
        "icon": "terminal",
        "category": "Automation",
    }
    CONFIG_SCHEMA = {
        "name": {"label": "Name", "type": "text", "required": True},
        "access_token": {
            "label": "CLI-Zugriffstoken",
            "type": "generated_secret",
            "required": True,
            "secret": True,
            "help": "Eigener Bearer-Token ausschließlich für dieses CLI-Portal.",
        },
        "allowed_commands": {
            "label": "Erlaubte Befehle",
            "type": "command_checkboxes",
            "default": "*",
        },
        "ip_allowlist": {
            "label": "IP-Allowlist",
            "type": "text",
            "help": "Optional, kommagetrennte IP-Adressen der erlaubten CLI-Clients.",
        },
    }
    REQUIRED = ("name", "access_token")
