"""Gunicorn configuration for the LANaxy web service.

LANaxy starts portal listeners (MQTT, Telegram and Discord) inside the Flask
application process. One worker with multiple threads prevents those listeners
from being started more than once while still allowing concurrent requests.
"""

import os
from pathlib import Path

import yaml


def _configured_bind() -> str:
    config_path = Path(os.environ.get("LANAXY_CONFIG", "/etc/lanaxy/config.yaml"))
    host = os.environ.get("LANAXY_WEB_HOST", "").strip()
    port_value = os.environ.get("LANAXY_WEB_PORT", "").strip()

    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            web = config.get("web", {}) if isinstance(config, dict) else {}
            host = host or str(web.get("host", "0.0.0.0")).strip()
            port_value = port_value or str(web.get("port", 8090)).strip()
        except (OSError, yaml.YAMLError):
            pass

    host = host or "0.0.0.0"
    if any(character.isspace() for character in host):
        raise RuntimeError("Ungültige LANaxy Web-Host-Konfiguration.")
    try:
        port = int(port_value or 8090)
    except ValueError as error:
        raise RuntimeError("Ungültiger LANaxy Web-Port.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("Der LANaxy Web-Port muss zwischen 1 und 65535 liegen.")
    return f"{host}:{port}"


bind = _configured_bind()
workers = 1
worker_class = "gthread"
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
pidfile = "/run/lanaxy/lanaxy-web.pid"
errorlog = "-"
accesslog = None
loglevel = "info"
capture_output = True
worker_tmp_dir = "/run/lanaxy"
