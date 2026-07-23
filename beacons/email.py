from beacons.base import BaseBeacon

class Beacon(BaseBeacon):
    BEACON={"id":"email","name":"E-Mail","version":"1.0.0","author":"LANaxy","description":"Sendet Benachrichtigungen über einen SMTP-Server.","icon":"email","category":"Nachrichten"}
    CONFIG_SCHEMA={
        "name":{"label":"Name","type":"text","required":True},
        "smtp_host":{"label":"SMTP-Server","type":"text","required":True},
        "smtp_port":{"label":"SMTP-Port","type":"number","default":587,"required":True},
        "encryption":{"label":"Verschlüsselung","type":"select","default":"starttls","options":["starttls","ssl","none"]},
        "username":{"label":"Benutzername","type":"text"},
        "password":{"label":"Passwort","type":"password","secret":True},
        "sender":{"label":"Absender","type":"text","required":True},
        "recipients":{"label":"Empfänger","type":"text","required":True,"help":"Mehrere Adressen durch Komma trennen."},
        "subject_prefix":{"label":"Betreff-Präfix","type":"text","default":"[LANaxy]"},
        "timeout":{"label":"Timeout (Sekunden)","type":"number","default":15},
    }
    REQUIRED=("smtp_host","sender","recipients")
    def send(self,notification):
        from notifications import send_email
        send_email(self.config,notification)
