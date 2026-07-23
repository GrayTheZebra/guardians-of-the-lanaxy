from beacons.base import BaseBeacon

class Beacon(BaseBeacon):
    BEACON={"id":"telegram","name":"Telegram","version":"1.0.0","author":"LANaxy","description":"Sendet Meldungen über einen Telegram-Bot.","icon":"telegram","category":"Messenger"}
    CONFIG_SCHEMA={
        "name":{"label":"Name","type":"text","required":True},
        "bot_token":{"label":"Bot-Token","type":"password","secret":True,"required":True},
        "chat_id":{"label":"Chat-ID","type":"text","required":True},
        "timeout":{"label":"Timeout (Sekunden)","type":"number","default":10},
    }
    REQUIRED=("bot_token","chat_id")
    def send(self,notification):
        from notifications import send_telegram
        send_telegram(self.config,notification)
