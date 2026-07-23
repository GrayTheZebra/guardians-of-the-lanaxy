import copy
import re

from custom_beacons import discover_beacons, resolve_beacon_class


SECRET_PLACEHOLDER = "••••••••"


def beacon_catalog():
    return {
        item["module"]: item
        for item in discover_beacons()
        if item.get("status") == "loaded"
    }


def slugify(value):
    value = value.lower().strip()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value)).strip("_") or "beacon"


def next_id(items, name):
    base = slugify(name)
    existing = {item.get("id") for item in items}
    number = 1
    while f"{base}_{number}" in existing:
        number += 1
    return f"{base}_{number}"




def next_name(items, base_name):
    """Return a human-readable unique name such as Telegram, Telegram 2, ..."""
    base_name = str(base_name or "Beacon").strip() or "Beacon"
    existing = {
        str(item.get("name", "")).strip().casefold()
        for item in items
        if isinstance(item, dict)
    }
    if base_name.casefold() not in existing:
        return base_name
    number = 2
    while f"{base_name} {number}".casefold() in existing:
        number += 1
    return f"{base_name} {number}"

def form_value(form, key, field, existing):
    raw = form.get(key)
    if field.get("secret") and raw == SECRET_PLACEHOLDER:
        return existing.get(key)
    if field.get("type") == "checkbox":
        return raw == "1"
    if raw is None or raw.strip() == "":
        return None
    if field.get("type") == "number":
        return int(raw)
    return raw.strip()


def build_channel(form, beacon_type, existing=None, all_channels=None):
    existing = copy.deepcopy(existing or {})
    catalog = beacon_catalog()
    metadata = catalog.get(beacon_type)
    if metadata is None:
        raise ValueError(f"Unbekannter Beacon-Typ: {beacon_type}")

    channel = existing
    channel["type"] = beacon_type

    for key, field in metadata["schema"].items():
        value = form_value(form, key, field, existing)
        if value is None:
            if key not in existing and "default" in field:
                value = field["default"]
            elif not field.get("required"):
                channel.pop(key, None)
                continue
        channel[key] = value

    if not channel.get("name"):
        raise ValueError("Bitte einen Namen eingeben.")

    channel["enabled"] = form.get("enabled") == "1"

    if not channel.get("id"):
        channel["id"] = next_id(all_channels or [], channel["name"])

    resolve_beacon_class(beacon_type).validate_config(channel)
    return channel


def find_channel(config, channel_id):
    return next(
        (
            item
            for item in config.get("notifications", {}).get("channels", [])
            if item.get("id") == channel_id
        ),
        None,
    )
