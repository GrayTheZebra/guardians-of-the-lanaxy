from beacons.base import BaseBeacon

class Beacon(BaseBeacon):
    BEACON={"id":"webhook","name":"Webhook","version":"1.0.0","author":"LANaxy","description":"Sendet Ereignisse als JSON per HTTP.","icon":"webhook","category":"Entwickler"}
    CONFIG_SCHEMA={
        "name":{
            "label":"Name","type":"text","required":True,
            "help":"Interner Anzeigename des Beacons, zum Beispiel „ioBroker Webhook“ oder „n8n Alarmierung“."
        },
        "url":{
            "label":"URL","type":"url","required":True,
            "help":"Vollständige Zieladresse, an die LANaxy den JSON-Body sendet, zum Beispiel http://192.168.0.50:1880/lanaxy."
        },
        "method":{
            "label":"Methode","type":"select","default":"POST","options":["POST","PUT","PATCH"],
            "help":"HTTP-Methode des Zielsystems. Für neue Webhooks ist POST normalerweise die richtige Wahl."
        },
        "bearer_token":{
            "label":"Bearer-Token","type":"password","secret":True,
            "help":"Optional. Wird als Header „Authorization: Bearer …“ gesendet. Leer lassen, wenn das Ziel keine Bearer-Authentifizierung nutzt."
        },
        "headers":{
            "label":"Zusätzliche Header","type":"textarea",
            "help":"Optional, ein Header pro Zeile. Beispiel: X-API-Key: geheim. Content-Type und User-Agent setzt LANaxy automatisch."
        },
        "timeout":{
            "label":"Timeout (Sekunden)","type":"number","default":10,
            "help":"Maximale Wartezeit auf die Antwort des Zielsystems. Werte zwischen 5 und 15 Sekunden sind meist sinnvoll."
        },
        "verify_tls":{
            "label":"TLS-Zertifikat prüfen","type":"checkbox","default":True,
            "help":"Bei HTTPS wird das Zertifikat geprüft. Nur für interne Ziele mit bewusst selbstsigniertem Zertifikat deaktivieren."
        },
    }
    REQUIRED=("url",)
    def send(self,notification):
        from notifications import send_webhook
        send_webhook(self.config,notification)
