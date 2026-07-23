from beacons.base import BaseBeacon

class Beacon(BaseBeacon):
    BEACON={"id":"mqtt","name":"MQTT","version":"1.0.0","author":"LANaxy","description":"Sendet Ereignisse als JSON an einen MQTT-Broker.","icon":"mqtt","category":"Netzwerk"}
    CONFIG_SCHEMA={
        "name":{"label":"Name","type":"text","required":True},
        "host":{"label":"Host oder IP","type":"text","required":True},
        "port":{"label":"Port","type":"number","default":1883,"required":True},
        "username":{"label":"Benutzername","type":"text"},
        "password":{"label":"Passwort","type":"password","secret":True},
        "topic":{"label":"Topic","type":"text","default":"lanaxy/notifications","required":True},
        "qos":{"label":"QoS","type":"select","default":"0","options":["0","1","2"]},
        "retain":{"label":"Retain","type":"checkbox","default":False},
        "tls":{"label":"TLS verwenden","type":"checkbox","default":False},
        "client_id":{"label":"Client-ID","type":"text"},
    }
    REQUIRED=("host","topic")
    def send(self,notification):
        from notifications import send_mqtt
        send_mqtt(self.config,notification)
