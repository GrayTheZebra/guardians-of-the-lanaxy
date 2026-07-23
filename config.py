from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "/etc/lanaxy/config.yaml"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)

    if not config_path.is_file():
        raise FileNotFoundError(f"Konfiguration nicht gefunden: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError(f"Ungültige oder leere Konfiguration: {config_path}")

    mqtt_config = config.get("mqtt")
    if mqtt_config is not None and not isinstance(mqtt_config, dict):
        raise ValueError("Der optionale Konfigurationsblock 'mqtt' muss ein Objekt sein.")

    checks = config.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("Der Konfigurationsblock 'checks' muss eine Liste sein.")

    return config
