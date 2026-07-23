from beacons.base import BaseBeacon


class Beacon(BaseBeacon):
    BEACON = {
        "id": "get_webhook",
        "name": "GET-Webhook",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "Sendet eine reduzierte Meldung als URL-Parameter per HTTP GET.",
        "icon": "webhook",
        "category": "Entwickler",
    }

    CONFIG_SCHEMA = {
        "name": {
            "label": "Name",
            "type": "text",
            "required": True,
            "help": "Interner Anzeigename, zum Beispiel „ioBroker GET-Webhook“.",
        },
        "url": {
            "label": "URL",
            "type": "url",
            "required": True,
            "help": "Zieladresse ohne LANaxy-Parameter. Vorhandene eigene Query-Parameter bleiben erhalten.",
        },
        "query_template": {
            "label": "Query",
            "type": "textarea",
            "required": True,
            "default": "status={status}&guardian={guardien}&message={text}&timestamp={date}",
            "help": (
                "Frei editierbare Query-Zeichenfolge. Unterstützte Platzhalter: "
                "{status}, {guardian} oder {guardien}, {message} oder {text}, "
                "{timestamp} oder {date}, {title} und {kind}. Feste Parameter "
                "können beliebig ergänzt werden, zum Beispiel action=red_on."
            ),
        },
        "bearer_token": {
            "label": "Bearer-Token",
            "type": "password",
            "secret": True,
            "help": "Optional. Wird sicher im Authorization-Header und nicht in der URL gesendet.",
        },
        "headers": {
            "label": "Zusätzliche Header",
            "type": "textarea",
            "help": "Optional, ein Header pro Zeile, zum Beispiel X-API-Key: geheim.",
        },
        "timeout": {
            "label": "Timeout (Sekunden)",
            "type": "number",
            "default": 10,
            "help": "Maximale Wartezeit auf die Antwort des Zielsystems.",
        },
        "verify_tls": {
            "label": "TLS-Zertifikat prüfen",
            "type": "checkbox",
            "default": True,
            "help": "Bei HTTPS das Zertifikat prüfen. Nur bei bewusst selbstsignierten internen Zertifikaten deaktivieren.",
        },
    }

    REQUIRED = ("url", "query_template")

    @classmethod
    def validate_config(cls, config):
        super().validate_config(config)
        query_template = str(config.get("query_template", ""))
        if "\n" in query_template or "\r" in query_template:
            raise ValueError("Die GET-Webhook-Query darf nur aus einer Zeile bestehen.")

    def send(self, notification):
        from notifications import send_get_webhook
        send_get_webhook(self.config, notification)
