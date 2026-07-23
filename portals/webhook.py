from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "webhook",
        "name": "Webhook",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Steuert LANaxy über eine eigene, geschützte Webhook-URL.",
        "icon": "webhook",
        "category": "Automation",
    }
    CONFIG_SCHEMA = {
        "name": {"label": "Name", "type": "text", "required": True},
        "webhook_secret": {
            "label": "Webhook-Schlüssel",
            "type": "generated_secret",
            "required": True,
            "secret": True,
            "help": "Wird automatisch erzeugt und ist Bestandteil der Webhook-URL.",
        },
        "allowed_commands": {
            "label": "Erlaubte Befehle",
            "type": "command_checkboxes",
            "default": "*",
        },
        "ip_allowlist": {
            "label": "IP-Allowlist",
            "type": "text",
            "help": "Optional, kommagetrennte IP-Adressen, die den Webhook aufrufen dürfen.",
        },
    }
    REQUIRED = ("name", "webhook_secret")
