import copy
import re


WIDGET_CATALOG = {
    "platform_status": {
        "name": "Plattformstatus",
        "description": "Guardians, Beacons, Portals und Rules.",
        "default_size": "full",
        "singleton": True,
    },
    "problems": {
        "name": "Aktuelle Probleme",
        "description": "Guardians mit Warning oder Critical.",
        "default_size": "wide",
        "singleton": True,
    },
    "runtime": {
        "name": "Runtime Control",
        "description": "Mute, Wartungen und pausierte Rules.",
        "default_size": "normal",
        "singleton": True,
    },
    "incidents": {
        "name": "Offene Incidents",
        "description": "Offene Ausfälle und Quittierungen.",
        "default_size": "wide",
        "singleton": True,
    },
    "events": {
        "name": "Letzte Ereignisse",
        "description": "Die neuesten Protokolleinträge.",
        "default_size": "wide",
        "singleton": True,
    },
    "system_health": {
        "name": "Systemgesundheit",
        "description": "Kompakte Zusammenfassung des Systems.",
        "default_size": "normal",
        "singleton": True,
    },
    "beacons": {
        "name": "Beacon-Status",
        "description": "Aktive Beacons und letzte Versandfehler.",
        "default_size": "normal",
        "singleton": True,
    },
    "portals": {
        "name": "Portal-Status",
        "description": "Aktive Portals und Verbindungszustand.",
        "default_size": "normal",
        "singleton": True,
    },
    "rules": {
        "name": "Rule-Status",
        "description": "Aktive und pausierte Rules.",
        "default_size": "normal",
        "singleton": True,
    },
    "guardian": {
        "name": "Einzelner Guardian",
        "description": "Status eines ausgewählten Guardians.",
        "default_size": "normal",
        "requires_target": True,
    },
    "guardian_group": {
        "name": "Guardian-Gruppe",
        "description": "Kompakte Liste einer Guardian-Gruppe.",
        "default_size": "wide",
        "requires_target": True,
    },
    "text": {
        "name": "Textblock",
        "description": "Eigene Überschrift und kurzer Text.",
        "default_size": "normal",
    },
}


DEFAULT_LAYOUT = [
    {"id": "platform_status_1", "type": "platform_status", "size": "full"},
    {"id": "problems_1", "type": "problems", "size": "wide"},
    {"id": "runtime_1", "type": "runtime", "size": "normal"},
    {"id": "events_1", "type": "events", "size": "wide"},
    {"id": "system_health_1", "type": "system_health", "size": "normal"},
]


VALID_SIZES = {"small", "normal", "wide", "full"}
SAFE_ID = re.compile(r"^[a-z0-9_]+$")


def default_layout():
    return copy.deepcopy(DEFAULT_LAYOUT)


def normalize_layout(value):
    if not isinstance(value, list):
        return default_layout()

    normalized = []
    seen_ids = set()
    singleton_types = set()

    for raw in value[:40]:
        if not isinstance(raw, dict):
            continue

        widget_type = str(raw.get("type", "")).strip()
        metadata = WIDGET_CATALOG.get(widget_type)
        if metadata is None:
            continue

        widget_id = str(raw.get("id", "")).strip()
        if not SAFE_ID.fullmatch(widget_id) or widget_id in seen_ids:
            continue

        if metadata.get("singleton") and widget_type in singleton_types:
            continue

        size = str(raw.get("size", metadata["default_size"]))
        if size not in VALID_SIZES:
            size = metadata["default_size"]

        widget = {
            "id": widget_id,
            "type": widget_type,
            "size": size,
        }

        target = str(raw.get("target", "")).strip()
        if target:
            widget["target"] = target

        title = str(raw.get("title", "")).strip()[:100]
        content = str(raw.get("content", "")).strip()[:2000]
        if title:
            widget["title"] = title
        if content:
            widget["content"] = content

        normalized.append(widget)
        seen_ids.add(widget_id)
        if metadata.get("singleton"):
            singleton_types.add(widget_type)

    return normalized or default_layout()


def next_widget_id(layout, widget_type):
    used = {item.get("id") for item in layout}
    counter = 1
    while f"{widget_type}_{counter}" in used:
        counter += 1
    return f"{widget_type}_{counter}"
