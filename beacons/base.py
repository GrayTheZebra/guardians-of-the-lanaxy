class BaseBeacon:
    BEACON = {
        "id": "base",
        "name": "Base Beacon",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "",
        "icon": "beacon",
        "category": "Allgemein",
    }
    CONFIG_SCHEMA = {}
    REQUIRED = ()

    def __init__(self, config):
        self.config = config

    @classmethod
    def validate_config(cls, config):
        missing = [
            key for key in cls.REQUIRED
            if config.get(key) in (None, "")
        ]
        if missing:
            raise ValueError(
                "Fehlende Beacon-Konfiguration: "
                + ", ".join(missing)
            )

    def send(self, notification):
        raise NotImplementedError
