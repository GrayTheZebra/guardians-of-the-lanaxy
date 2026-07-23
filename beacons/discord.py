from beacons.base import BaseBeacon

class Beacon(BaseBeacon):
    BEACON={"id":"discord","name":"Discord","version":"1.0.0","author":"LANaxy","description":"Sendet formatierte Meldungen an einen Discord-Webhook.","icon":"discord","category":"Messenger"}
    CONFIG_SCHEMA={
        "name":{"label":"Name","type":"text","required":True},
        "webhook_url":{"label":"Webhook-URL","type":"url","required":True,"secret":True},
        "username":{"label":"Anzeigename","type":"text","default":"LANaxy"},
        "avatar_url":{"label":"Avatar-URL","type":"url"},
        "mention":{"label":"Erwähnung","type":"text","help":"Optional, z. B. @everyone oder eine Rollen-ID."},
        "timeout":{"label":"Timeout (Sekunden)","type":"number","default":10},
    }
    REQUIRED=("webhook_url",)
    def send(self,notification):
        from notifications import send_discord
        send_discord(self.config,notification)
