import json
import urllib.request
import urllib.error
from copy import deepcopy
from web.config_service import next_guardian_id

AI_SECRET_PLACEHOLDER = "••••••••"

def provider_catalog():
    return {
        "openai": {"name": "OpenAI", "default_base_url": "https://api.openai.com/v1", "default_model": "gpt-5-mini", "implemented": True},
        "openai_compatible": {"name": "OpenAI-kompatible API", "default_base_url": "", "default_model": "", "implemented": False},
        "ollama": {"name": "Ollama", "default_base_url": "http://127.0.0.1:11434/v1", "default_model": "", "implemented": False},
    }

def _catalog_payload(catalog):
    result = []
    for module, item in catalog.items():
        schema = {}
        for key, field in item.get("schema", {}).items():
            schema[key] = {k: v for k, v in field.items() if k in {"type", "required", "default", "options", "description", "label"}}
        result.append({"module": module, "name": item.get("name", module), "category": item.get("category", "other"), "schema": schema})
    return result

def _extract_output_text(response):
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts)

def generate_plan(ai_config, request_text, catalog, current_config):
    provider = ai_config.get("provider", "openai")
    if provider != "openai":
        raise ValueError("Dieser Anbieter ist vorbereitet, aber in dieser Testversion noch nicht aktiviert.")
    api_key = ai_config.get("api_key", "").strip()
    if not api_key:
        raise ValueError("Bitte zuerst einen OpenAI API-Key in den KI-Einstellungen speichern.")
    base_url = (ai_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = ai_config.get("model") or "gpt-5-mini"
    existing = [{"id": c.get("id"), "name": c.get("name"), "guardian": c.get("guardian"), "group": c.get("group")} for c in current_config.get("checks", [])]
    existing_beacons = [{"id": b.get("id"), "name": b.get("name"), "type": b.get("type"), "enabled": b.get("enabled", True)} for b in current_config.get("notifications", {}).get("channels", [])]
    instructions = (
        "Du bist der LANaxy-Konfigurationsplaner. Erzeuge ausschließlich JSON. "
        "Verwende nur Guardian-Module aus dem Katalog und nur deren bekannte Konfigurationsfelder. "
        "Erfinde keine Zugangsdaten. Fehlende Secrets oder Pflichtwerte kommen in missing_fields. "
        "dependencies referenzieren Guardian-Namen aus diesem Plan oder IDs bestehender Guardians. "
        "Rules und Beacons nur anlegen, wenn der Wunsch sie ausdrücklich verlangt. "
        "Beim Proxmox API Guardian darf node leer bleiben; LANaxy erkennt den Node automatisch. Setze node nur, wenn der Benutzer den exakten Proxmox-Node-Namen ausdrücklich nennt. "
        "Bei Proxmox-Gastprüfungen darf vmid leer bleiben, wenn der Benutzer keine exakte VM-/LXC-ID nennt; LANaxy kann VMs und LXCs anschließend automatisch abrufen. "
        "Wenn ein gewünschter Beacon bereits unter existing_beacons existiert, lege keinen neuen Beacon an, sondern referenziere in beacon_names exakt dessen Namen. "
        "Konfigurationen werden als Liste aus key und value_json geliefert. value_json enthält immer einen gültigen JSON-Wert als String, zum Beispiel true, 8006 oder \"192.168.0.24\"."
    )
    prompt = {"request": request_text, "available_guardians": _catalog_payload(catalog), "existing_guardians": existing, "existing_beacons": existing_beacons}
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "guardians": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
                "temp_id": {"type": "string"}, "type": {"type": "string"}, "name": {"type": "string"}, "enabled": {"type": "boolean"},
                "group": {"type": "string"}, "config": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"key": {"type": "string"}, "value_json": {"type": "string"}}, "required": ["key", "value_json"]}},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "missing_fields": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "array", "items": {"type": "string"}}
            }, "required": ["temp_id", "type", "name", "enabled", "group", "config", "depends_on", "missing_fields", "notes"]}},
            "beacons": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
                "type": {"type": "string"}, "name": {"type": "string"}, "config": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"key": {"type": "string"}, "value_json": {"type": "string"}}, "required": ["key", "value_json"]}},
                "missing_fields": {"type": "array", "items": {"type": "string"}}
            }, "required": ["type", "name", "config", "missing_fields"]}},
            "rules": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
                "name": {"type": "string"}, "statuses": {"type": "array", "items": {"type": "string"}},
                "guardian_names": {"type": "array", "items": {"type": "string"}},
                "beacon_names": {"type": "array", "items": {"type": "string"}},
                "root_cause_only": {"type": "boolean"}
            }, "required": ["name", "statuses", "guardian_names", "beacon_names", "root_cause_only"]}},
            "warnings": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["summary", "guardians", "beacons", "rules", "warnings"]
    }
    payload = {"model": model, "instructions": instructions, "input": json.dumps(prompt, ensure_ascii=False),
               "text": {"verbosity": "low", "format": {"type": "json_schema", "name": "lanaxy_plan", "strict": True, "schema": schema}}}
    if model.startswith("gpt-5"):
        payload["reasoning"] = {"effort": "low"}
    req = urllib.request.Request(base_url + "/responses", data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            pass
        raise ValueError(f"OpenAI-Anfrage fehlgeschlagen: {detail}") from error
    except Exception as error:
        raise ValueError(f"OpenAI ist nicht erreichbar: {error}") from error
    text = _extract_output_text(body)
    if not text:
        raise ValueError("OpenAI hat keinen auswertbaren Plan zurückgegeben.")
    plan = json.loads(text)
    raw_plan = deepcopy(plan)
    plan = _resolve_existing_beacons(plan, current_config, request_text)
    plan["_debug"] = {
        "raw_response": text,
        "raw_plan": raw_plan,
        "existing_beacons": existing_beacons,
        "resolved_rules": [
            {
                "name": rule.get("name"),
                "requested_beacons": raw_rule.get("beacon_names", []),
                "resolved_beacons": rule.get("beacon_names", []),
            }
            for rule, raw_rule in zip(plan.get("rules", []), raw_plan.get("rules", []))
        ],
    }
    return plan

def _decode_config(entries, object_name):
    if isinstance(entries, dict):
        return entries
    result = {}
    for entry in entries or []:
        key = str(entry.get("key", "")).strip()
        if not key:
            raise ValueError(f"{object_name}: Konfigurationsfeld ohne Schlüssel.")
        try:
            result[key] = json.loads(entry.get("value_json", "null"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{object_name}: ungültiger JSON-Wert für {key}.") from error
    return result


def _coerce_schema_value(value, field, object_name, key):
    field_type = field.get("type", "text")
    if field_type not in {"number", "integer"}:
        return value
    if isinstance(value, bool):
        raise ValueError(f"{object_name}: {key} ist keine gültige Zahl.")
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return value
        try:
            value = float(normalized)
        except ValueError as error:
            raise ValueError(f"{object_name}: {key} ist keine gültige Zahl.") from error
    if isinstance(value, (int, float)):
        # LANaxy-Zeit- und Zählerfelder arbeiten ganzzahlig. 60,0 / 60.0 wird zu 60.
        if field_type == "integer" or float(value).is_integer():
            return int(float(value))
        return float(value)
    raise ValueError(f"{object_name}: {key} ist keine gültige Zahl.")


def _beacon_reference_key(value):
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _resolve_existing_beacons(plan, current_config, request_text=""):
    existing = [
        beacon for beacon in current_config.get("notifications", {}).get("channels", [])
        if beacon.get("id") and beacon.get("name") and beacon.get("enabled", True)
    ]
    if not existing:
        return plan

    request_folded = (request_text or "").casefold()
    request_key = _beacon_reference_key(request_text)
    by_exact = {}
    for beacon in existing:
        by_exact[str(beacon["name"]).strip().casefold()] = beacon
        by_exact[str(beacon["id"]).strip().casefold()] = beacon
        by_exact[_beacon_reference_key(beacon["name"])] = beacon
        by_exact[_beacon_reference_key(beacon["id"])] = beacon

    explicitly_mentioned = []
    for beacon in existing:
        name = str(beacon["name"]).strip()
        beacon_id = str(beacon["id"]).strip()
        if (
            name.casefold() in request_folded
            or beacon_id.casefold() in request_folded
            or _beacon_reference_key(name) in request_key
            or _beacon_reference_key(beacon_id) in request_key
        ):
            explicitly_mentioned.append(beacon)

    request_wants_beacon = any(word in request_folded for word in ("beacon", "benachrichtig", "melden", "alarm", "mqtt"))
    mqtt_beacons = [beacon for beacon in existing if str(beacon.get("type", "")).casefold() == "mqtt"]

    if not explicitly_mentioned and request_wants_beacon:
        if len(existing) == 1:
            explicitly_mentioned = existing[:]
        elif "mqtt" in request_folded and len(mqtt_beacons) == 1:
            explicitly_mentioned = mqtt_beacons[:]

    for rule in plan.get("rules", []):
        resolved = []
        for reference in rule.get("beacon_names", []):
            reference_text = str(reference).strip()
            reference_folded = reference_text.casefold()
            beacon = by_exact.get(reference_folded) or by_exact.get(_beacon_reference_key(reference_text))
            if not beacon:
                # Let "MQTT Beacon", "iBroker MQTT" etc. match a single compatible existing beacon.
                candidates = [
                    item for item in existing
                    if _beacon_reference_key(reference_text) in _beacon_reference_key(item["name"])
                    or _beacon_reference_key(item["name"]) in _beacon_reference_key(reference_text)
                ]
                if len(candidates) == 1:
                    beacon = candidates[0]
                elif "mqtt" in reference_folded and len(mqtt_beacons) == 1:
                    beacon = mqtt_beacons[0]
            if beacon:
                resolved.append(beacon["name"])

        if not resolved and explicitly_mentioned:
            resolved = [beacon["name"] for beacon in explicitly_mentioned]

        # A rule requested by the user must never silently lose an unambiguous existing beacon.
        if not resolved and request_wants_beacon and len(existing) == 1:
            resolved = [existing[0]["name"]]

        rule["beacon_names"] = list(dict.fromkeys(resolved))
    return plan


def _normalize_guardian_type(value, catalog):
    raw = str(value or "").strip()
    if raw in catalog:
        return raw

    def key(item):
        return "".join(character for character in str(item).casefold() if character.isalnum())

    wanted = key(raw)
    aliases = {}
    for module, metadata in catalog.items():
        candidates = {
            module,
            metadata.get("name", ""),
            metadata.get("title", ""),
            f"{metadata.get('name', '')} Guardian",
        }
        for candidate in candidates:
            candidate_key = key(candidate)
            if candidate_key:
                aliases[candidate_key] = module

    explicit = {
        "proxmoxapiguardian": "proxmox_api",
        "speicherplatzguardian": "storage",
        "storageguardian": "storage",
        "smartguardian": "smart",
        "smartdiskguardian": "smart",
        "smartdriveguardian": "smart",
    }
    aliases.update({key(alias): module for alias, module in explicit.items() if module in catalog})

    if wanted in aliases:
        return aliases[wanted]

    matches = [module for alias, module in aliases.items() if wanted and (wanted in alias or alias in wanted)]
    matches = list(dict.fromkeys(matches))
    return matches[0] if len(matches) == 1 else raw


def validate_plan(plan, catalog, current_config):
    errors = []
    names = set()
    temp_ids = set()
    existing_ids = {c.get("id") for c in current_config.get("checks", [])}
    for guardian in plan.get("guardians", []):
        try:
            guardian["config"] = _decode_config(guardian.get("config", []), guardian.get("name") or "Guardian")
        except ValueError as error:
            errors.append(str(error))
            guardian["config"] = {}
        guardian["type"] = _normalize_guardian_type(guardian.get("type"), catalog)
        if guardian.get("type") not in catalog:
            errors.append(f"Unbekannter Guardian-Typ: {guardian.get('type')}")
        if not guardian.get("name"):
            errors.append("Ein Guardian hat keinen Namen.")
        if guardian.get("name") in names:
            errors.append(f"Doppelter Guardian-Name im Plan: {guardian.get('name')}")
        names.add(guardian.get("name"))
        temp_ids.add(guardian.get("temp_id"))
        schema = catalog.get(guardian.get("type"), {}).get("schema", {})
        unknown = set(guardian.get("config", {})) - set(schema)
        if unknown:
            errors.append(f"{guardian.get('name')}: unbekannte Felder: {', '.join(sorted(unknown))}")
        config = guardian.get("config", {})
        for key in list(config):
            if key not in schema:
                continue
            try:
                config[key] = _coerce_schema_value(config[key], schema[key], guardian.get("name") or "Guardian", key)
            except ValueError as error:
                errors.append(str(error))
        missing = set()
        for key, field in schema.items():
            if not field.get("required") or key in {"name", "id", "device_id"}:
                continue
            value = config.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.add(key)
        guardian["missing_fields"] = sorted(missing)
    for beacon in plan.get("beacons", []):
        try:
            beacon["config"] = _decode_config(beacon.get("config", []), beacon.get("name") or "Beacon")
        except ValueError as error:
            errors.append(str(error))
            beacon["config"] = {}
    allowed_refs = temp_ids | names | existing_ids
    for guardian in plan.get("guardians", []):
        for dependency in guardian.get("depends_on", []):
            if dependency not in allowed_refs:
                errors.append(f"{guardian.get('name')}: unbekannte Abhängigkeit {dependency}")
    plan["valid"] = not errors
    plan["errors"] = errors
    return plan

def apply_plan(plan, current_config):
    if not plan.get("valid"):
        raise ValueError("Der Plan enthält Validierungsfehler.")
    unresolved = [f"{g['name']}: {', '.join(g.get('missing_fields', []))}" for g in plan.get("guardians", []) if g.get("missing_fields")]
    unresolved += [f"Beacon {b['name']}: {', '.join(b.get('missing_fields', []))}" for b in plan.get("beacons", []) if b.get("missing_fields")]
    if unresolved:
        raise ValueError("Vor dem Anlegen fehlen Pflichtangaben: " + "; ".join(unresolved))
    config = deepcopy(current_config)
    checks = config.setdefault("checks", [])
    id_map = {}
    new_checks = []
    for guardian in plan.get("guardians", []):
        guardian_id = next_guardian_id(config, guardian["name"])
        id_map[guardian["temp_id"]] = guardian_id
        id_map[guardian["name"]] = guardian_id
        check = {"id": guardian_id, "device_id": guardian_id, "guardian": guardian["type"], "name": guardian["name"],
                 "enabled": bool(guardian.get("enabled", True))}
        if guardian.get("group"):
            check["group"] = guardian["group"]
        check.update(deepcopy(guardian.get("config", {})))
        checks.append(check)
        new_checks.append(check)
    existing = {c.get("id") for c in checks}
    for guardian, check in zip(plan.get("guardians", []), new_checks):
        dependencies = [id_map.get(d, d) for d in guardian.get("depends_on", [])]
        dependencies = [d for d in dependencies if d in existing and d != check["id"]]
        if dependencies:
            check["depends_on"] = dependencies
    notifications = config.setdefault("notifications", {})
    channels = notifications.setdefault("channels", [])
    channel_map = {}
    for channel in channels:
        if not channel.get("id"):
            continue
        if channel.get("name"):
            channel_map[str(channel["name"]).strip().casefold()] = channel["id"]
        channel_map[str(channel["id"]).strip().casefold()] = channel["id"]
    existing_channel_ids = {c.get("id") for c in channels}
    for beacon in plan.get("beacons", []):
        base = next_guardian_id({"checks": [{"id": x} for x in existing_channel_ids]}, beacon["name"])
        existing_channel_ids.add(base)
        channel = {"id": base, "type": beacon["type"], "name": beacon["name"], "enabled": True}
        channel.update(deepcopy(beacon.get("config", {})))
        channels.append(channel)
        channel_map[str(beacon["name"]).strip().casefold()] = base
        channel_map[str(base).strip().casefold()] = base
    rules = notifications.setdefault("rules", [])
    existing_rule_ids = {r.get("id") for r in rules}
    for rule in plan.get("rules", []):
        rule_id = next_guardian_id({"checks": [{"id": x} for x in existing_rule_ids]}, rule["name"])
        existing_rule_ids.add(rule_id)
        guardian_ids = [id_map.get(n, n) for n in rule.get("guardian_names", []) if id_map.get(n, n) in existing]
        channel_ids = []
        for reference in rule.get("beacon_names", []):
            resolved = channel_map.get(str(reference).strip().casefold())
            if resolved in existing_channel_ids:
                channel_ids.append(resolved)
        channel_ids = list(dict.fromkeys(channel_ids))
        rules.append({"id": rule_id, "name": rule["name"], "enabled": True,
                      "statuses": rule.get("statuses") or ["warning", "critical", "recovery"],
                      "all_channels": not channel_ids, "channels": channel_ids,
                      "all_groups": True, "groups": [], "all_guardians": not guardian_ids, "guardians": guardian_ids,
                      "root_cause_only": bool(rule.get("root_cause_only")),
                      "quiet_hours_enabled": False, "quiet_start": "22:00", "quiet_end": "07:00",
                      "delay_seconds": 0, "repeat_minutes": 0, "repeat_count": 0})
    return config
