import ipaddress
from urllib.parse import urlparse


ALIASES = {
    "ha": "home_assistant",
    "homeassistant": "home_assistant",
    "home_assistant": "home_assistant",
    "iobroker": "iobroker",
    "node_red": "node_red",
    "nodered": "node_red",
    "mqtt": "mqtt",
    "mosquitto": "mqtt",
    "zigbee2mqtt": "zigbee2mqtt",
    "zwavejs": "zwave_js",
    "zwave_js": "zwave_js",
}

ROUTING_SENSITIVE = {
    "home_assistant",
    "iobroker",
    "node_red",
    "mqtt",
    "zigbee2mqtt",
    "zwave_js",
}


def normalize_family(value):
    value = str(value or "").lower().strip()
    value = value.removeprefix("custom:")
    value = value.replace("-", "_").replace(" ", "_")
    compact = value.replace("_", "")
    return ALIASES.get(value) or ALIASES.get(compact) or value


def metadata_family(metadata, module_name):
    explicit = metadata.get("service_family") if metadata else None
    if explicit:
        return normalize_family(explicit)
    return normalize_family(module_name)


def _walk_values(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_values(child, child_prefix)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_values(child, prefix)
    else:
        yield prefix.lower(), value


def normalize_endpoint(value):
    value = str(value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        port = parsed.port
        if host:
            return f"{host}:{port}" if port else host
    value = value.strip("[]/")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value


def endpoints_for(item):
    endpoints = set()
    interesting = (
        "host",
        "hostname",
        "server",
        "broker",
        "url",
        "base_url",
        "address",
        "ip",
    )
    ignored = (
        "user",
        "username",
        "password",
        "token",
        "topic",
        "name",
        "id",
    )

    for path, raw in _walk_values(item):
        leaf = path.split(".")[-1]
        if leaf in ignored:
            continue
        if any(key == leaf or path.endswith(f".{key}") for key in interesting):
            endpoint = normalize_endpoint(raw)
            if endpoint:
                endpoints.add(endpoint)
    return endpoints


def selected_items(rule, config):
    checks = config.get("checks", [])
    channels = config.get("notifications", {}).get("channels", [])

    if rule.get("all_guardians", True):
        selected_checks = [
            item for item in checks if item.get("enabled", True)
        ]
    else:
        selected_ids = set(rule.get("guardians", []))
        selected_checks = [
            item for item in checks if item.get("id") in selected_ids
        ]

    if rule.get("all_channels", True):
        selected_channels = [
            item for item in channels if item.get("enabled", True)
        ]
    else:
        selected_ids = set(rule.get("channels", []))
        selected_channels = [
            item for item in channels if item.get("id") in selected_ids
        ]

    return selected_checks, selected_channels


def analyze_rule(rule, config, guardian_catalog, beacon_catalog):
    findings = []
    checks, channels = selected_items(rule, config)

    for check in checks:
        guardian_type = str(check.get("guardian", ""))
        guardian_meta = guardian_catalog.get(guardian_type, {})
        guardian_family = metadata_family(
            guardian_meta,
            guardian_type,
        )
        guardian_endpoints = endpoints_for(check)

        for channel in channels:
            beacon_type = str(channel.get("type", ""))
            beacon_meta = beacon_catalog.get(beacon_type, {})
            beacon_family = metadata_family(
                beacon_meta,
                beacon_type,
            )
            beacon_endpoints = endpoints_for(channel)

            same_family = (
                guardian_family
                and guardian_family == beacon_family
                and guardian_family in ROUTING_SENSITIVE
            )
            shared_endpoints = (
                guardian_endpoints & beacon_endpoints
            )

            if same_family and (
                shared_endpoints
                or not guardian_endpoints
                or not beacon_endpoints
            ):
                findings.append({
                    "level": "error",
                    "code": "notification_loop",
                    "rule_id": rule.get("id", ""),
                    "rule_name": rule.get("name", ""),
                    "guardian_id": check.get("id", ""),
                    "guardian_name": check.get(
                        "name",
                        check.get("id", ""),
                    ),
                    "beacon_id": channel.get("id", ""),
                    "beacon_name": channel.get(
                        "name",
                        channel.get("id", ""),
                    ),
                    "message": (
                        f"{check.get('name', check.get('id'))} überwacht "
                        f"{guardian_family.replace('_', ' ')}, während "
                        f"{channel.get('name', channel.get('id'))} "
                        "Meldungen an denselben Dienst sendet. "
                        "Bei einem Ausfall könnte die Benachrichtigung "
                        "nicht zugestellt werden oder eine Schleife entstehen."
                    ),
                })
            elif same_family:
                findings.append({
                    "level": "warning",
                    "code": "same_service_family",
                    "rule_id": rule.get("id", ""),
                    "rule_name": rule.get("name", ""),
                    "guardian_id": check.get("id", ""),
                    "guardian_name": check.get(
                        "name",
                        check.get("id", ""),
                    ),
                    "beacon_id": channel.get("id", ""),
                    "beacon_name": channel.get(
                        "name",
                        channel.get("id", ""),
                    ),
                    "message": (
                        f"{check.get('name', check.get('id'))} und "
                        f"{channel.get('name', channel.get('id'))} "
                        f"verwenden beide {guardian_family.replace('_', ' ')}. "
                        "Prüfe, ob wirklich unterschiedliche Instanzen "
                        "verwendet werden."
                    ),
                })
            elif shared_endpoints:
                findings.append({
                    "level": "warning",
                    "code": "shared_endpoint",
                    "rule_id": rule.get("id", ""),
                    "rule_name": rule.get("name", ""),
                    "guardian_id": check.get("id", ""),
                    "guardian_name": check.get(
                        "name",
                        check.get("id", ""),
                    ),
                    "beacon_id": channel.get("id", ""),
                    "beacon_name": channel.get(
                        "name",
                        channel.get("id", ""),
                    ),
                    "message": (
                        f"{check.get('name', check.get('id'))} und "
                        f"{channel.get('name', channel.get('id'))} "
                        "verwenden dasselbe Zielsystem. Fällt dieses aus, "
                        "kann die Meldung möglicherweise nicht zugestellt werden."
                    ),
                })

    unique = {}
    for finding in findings:
        key = (
            finding["level"],
            finding["rule_id"],
            finding["guardian_id"],
            finding["beacon_id"],
            finding["code"],
        )
        unique[key] = finding
    return list(unique.values())


def analyze_config(config, guardian_catalog, beacon_catalog):
    findings = []
    for rule in config.get("notifications", {}).get("rules", []):
        if not rule.get("enabled", True):
            continue
        findings.extend(
            analyze_rule(
                rule,
                config,
                guardian_catalog,
                beacon_catalog,
            )
        )
    return findings


def blocking_findings(findings):
    return [
        item for item in findings if item.get("level") == "error"
    ]
