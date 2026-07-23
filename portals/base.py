class BasePortal:
    PORTAL = {
        "id": "base",
        "name": "Base Portal",
        "version": "1.0.0",
        "author": "LANaxy",
        "description": "",
        "icon": "portal",
        "category": "Allgemein",
    }
    CONFIG_SCHEMA = {}
    REQUIRED = ()
    BACKGROUND = False

    def __init__(self, config, command_handler, token_validator):
        self.config = config
        self.command_handler = command_handler
        self.token_validator = token_validator
        self.last_error = ""
        self.running = False

    @classmethod
    def validate_config(cls, config):
        missing = [
            key
            for key in cls.REQUIRED
            if config.get(key) in (None, "")
        ]
        if missing:
            raise ValueError(
                "Fehlende Portal-Konfiguration: " + ", ".join(missing)
            )

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def health(self):
        return {
            "running": self.running,
            "last_error": self.last_error,
        }

    def test(self):
        return self.health()
