import copy
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from config import load_config
from guardian_manager import load_guardian, resolve_guardian_class
from custom_guardians import list_custom_guardians, load_custom_module


SECRET_PLACEHOLDER = "••••••••"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def slugify_name(value: str) -> str:
    value = value.strip().lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)

    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "guardian"


def next_guardian_id(config: dict, guardian_name: str) -> str:
    base = slugify_name(guardian_name)
    existing = {
        str(check.get("id", ""))
        for check in config.get("checks", [])
    }

    number = 1
    candidate = f"{base}_{number}"

    while candidate in existing:
        number += 1
        candidate = f"{base}_{number}"

    return candidate


def configuration_inventory(config: dict) -> dict:
    """Return compact, human-readable contents of a LANaxy configuration."""
    def names(items: list, fallback: str) -> list[str]:
        result = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            value = (
                item.get("name")
                or item.get("label")
                or item.get("title")
                or item.get("id")
                or item.get("guardian")
                or item.get("type")
                or f"{fallback} {index}"
            )
            result.append(str(value))
        return result

    notifications = config.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}
    control = config.get("control", {})
    if not isinstance(control, dict):
        control = {}

    guardians = names(config.get("checks", []) if isinstance(config.get("checks", []), list) else [], "Guardian")
    beacons = names(notifications.get("channels", []) if isinstance(notifications.get("channels", []), list) else [], "Beacon")
    rules = names(notifications.get("rules", []) if isinstance(notifications.get("rules", []), list) else [], "Rule")
    portals = names(control.get("portals", []) if isinstance(control.get("portals", []), list) else [], "Portal")

    return {
        "guardians": len(guardians),
        "guardian_names": guardians,
        "beacons": len(beacons),
        "beacon_names": beacons,
        "rules": len(rules),
        "rule_names": rules,
        "portals": len(portals),
        "portal_names": portals,
    }



def prune_configuration_history(backup_dir: Path, keep: int = 100) -> dict[str, int]:
    """Keep only the newest configuration revisions and remove sidecars/orphans."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = max(1, int(keep or 100))
    revisions = sorted(
        backup_dir.glob("config-*.yaml"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed_yaml = 0
    removed_meta = 0
    for path in revisions[keep:]:
        path.unlink(missing_ok=True)
        removed_yaml += 1
        sidecar = path.with_suffix(".json")
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)
            removed_meta += 1

    valid_stems = {path.stem for path in revisions[:keep] if path.exists()}
    for sidecar in backup_dir.glob("config-*.json"):
        if sidecar.stem not in valid_stems:
            sidecar.unlink(missing_ok=True)
            removed_meta += 1

    for temporary in backup_dir.glob("*.tmp"):
        temporary.unlink(missing_ok=True)

    return {"history": removed_yaml, "metadata": removed_meta}

def get_nested(data: dict, dotted_key: str, default=None):
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def set_nested(data: dict, dotted_key: str, value):
    parts = dotted_key.split(".")
    target = data
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def delete_nested(data: dict, dotted_key: str):
    parts = dotted_key.split(".")
    target = data
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            return
        target = target[part]
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def discover_guardians() -> list[dict]:
    import importlib
    import pkgutil
    import guardians

    discovered = []

    for module_info in pkgutil.iter_modules(guardians.__path__):
        if module_info.name in {"base"}:
            continue

        try:
            module = importlib.import_module(f"guardians.{module_info.name}")
            guardian_class = getattr(module, "Guardian")
            metadata = copy.deepcopy(guardian_class.GUARDIAN)
            metadata["module"] = module_info.name
            metadata["schema"] = copy.deepcopy(
                getattr(guardian_class, "CONFIG_SCHEMA", {})
            )
            discovered.append(metadata)
        except Exception:
            continue

    for custom in list_custom_guardians():
        if custom.get("status") != "loaded":
            continue
        module = load_custom_module(custom["module"])
        cls = module.Guardian
        metadata = copy.deepcopy(cls.GUARDIAN)
        metadata["module"] = f"custom:{custom['module']}"
        metadata["schema"] = copy.deepcopy(getattr(cls, "CONFIG_SCHEMA", {}))
        metadata["source"] = "custom"
        discovered.append(metadata)

    return sorted(discovered, key=lambda item: item.get("name", item["module"]))


def convert_value(raw_value: str | None, field: dict):
    field_type = field.get("type", "text")

    if field_type == "checkbox":
        return raw_value in {"1", "true", "on", "yes"}

    if raw_value is None:
        return None

    raw_value = raw_value.strip()

    if raw_value == "":
        return None

    if field_type in {"number", "integer"}:
        normalized = raw_value.replace(",", ".")
        try:
            number = float(normalized)
        except ValueError as error:
            raise ValueError(f"Ungültiger Zahlenwert: {raw_value}") from error
        if not number.is_integer():
            raise ValueError(f"Für dieses Feld ist eine ganze Zahl erforderlich: {raw_value}")
        return int(number)

    return raw_value


def build_check_from_form(
    form,
    guardian_module: str,
    schema: dict,
    existing: dict | None = None,
    config: dict | None = None,
) -> dict:
    check = copy.deepcopy(existing or {})
    check["guardian"] = guardian_module

    for key, field in schema.items():
        if key == "device_id":
            continue
        raw = form.get(key)

        if field.get("secret") and raw == SECRET_PLACEHOLDER:
            continue

        value = convert_value(raw, field)

        if value is None:
            if not field.get("required"):
                delete_nested(check, key)
            continue

        set_nested(check, key, value)

    check["enabled"] = form.get("enabled", "1") in {"1", "true", "on", "yes"}

    group = form.get("group", "").strip()
    if group:
        check["group"] = group
    else:
        check.pop("group", None)

    tags = []
    for raw_tag in form.get("tags", "").split(","):
        tag = raw_tag.strip()
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
    if tags:
        check["tags"] = tags
    else:
        check.pop("tags", None)

    dependencies = [
        value
        for value in form.getlist("depends_on")
        if value and value != check.get("id")
    ]
    if dependencies:
        check["depends_on"] = dependencies
    else:
        check.pop("depends_on", None)

    if not check.get("name"):
        raise ValueError("Bitte einen Namen eingeben.")

    if not check.get("id"):
        if existing and existing.get("id"):
            check["id"] = existing["id"]
        else:
            check["id"] = next_guardian_id(
                config or {"checks": []},
                check["name"],
            )

    check["device_id"] = check["id"]

    check_id = check.get("id", "")
    if not SLUG_PATTERN.match(check_id):
        raise ValueError(
            "Die Check-ID darf nur Kleinbuchstaben, Zahlen, _ und - enthalten."
        )

    device_id = check.get("device_id", "")
    if not SLUG_PATTERN.match(device_id):
        raise ValueError(
            "Die Geräte-ID darf nur Kleinbuchstaben, Zahlen, _ und - enthalten."
        )

    return check


class ConfigService:
    def __init__(self, config_path: str, backup_dir: str):
        self.config_path = Path(config_path)
        self.backup_dir = Path(backup_dir)

    def load(self) -> dict:
        return load_config(str(self.config_path))

    def validate(self, config: dict):
        checks = config.get("checks", [])
        seen_ids = set()

        for check in checks:
            check_id = check.get("id")
            if check_id in seen_ids:
                raise ValueError(f"Doppelte Guardian-ID: {check_id}")
            seen_ids.add(check_id)

            missing_secrets = check.get("_import_missing_secrets", [])
            if missing_secrets:
                if check.get("enabled", True):
                    raise ValueError(
                        f"Guardian {check_id} kann wegen fehlender Zugangsdaten "
                        "nicht aktiviert werden."
                    )
                # The type still has to exist, but required secret fields are
                # intentionally absent until the user edits the imported Guardian.
                resolve_guardian_class(check["guardian"])
                continue

            load_guardian(check)

        graph = {}
        for check in checks:
            check_id = check.get("id")
            dependencies = check.get("depends_on", [])
            if isinstance(dependencies, str):
                dependencies = [dependencies]

            for dependency_id in dependencies:
                if dependency_id not in seen_ids:
                    raise ValueError(
                        f"Unbekannte Abhängigkeit bei {check_id}: "
                        f"{dependency_id}"
                    )
                if dependency_id == check_id:
                    raise ValueError(
                        f"Guardian {check_id} kann nicht von sich selbst abhängen."
                    )

            graph[check_id] = list(dependencies)

        visiting = set()
        visited = set()

        def visit(node):
            if node in visiting:
                raise ValueError(
                    "Zirkuläre Guardian-Abhängigkeit erkannt."
                )
            if node in visited:
                return

            visiting.add(node)
            for dependency in graph.get(node, []):
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    def save(self, config: dict):
        self.validate(config)

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_path = self.backup_dir / f"config-{stamp}.yaml"
            shutil.copy2(self.config_path, backup_path)
            try:
                old_config = load_config(str(self.config_path))
                metadata = {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    **configuration_inventory(old_config),
                }
                backup_path.with_suffix(".json").write_text(__import__("json").dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.config_path.with_suffix(".yaml.tmp")

        with temp_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                config,
                handle,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )

        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.config_path)

        history_keep = int(
            config.get("lanaxy", {}).get("config_history_keep", 100) or 100
        )
        prune_configuration_history(self.backup_dir, history_keep)

    def upsert_check(self, check: dict, original_id: str | None = None):
        config = self.load()
        checks = config.setdefault("checks", [])

        if original_id:
            for index, existing in enumerate(checks):
                if existing.get("id") == original_id:
                    checks[index] = check
                    break
            else:
                raise ValueError(f"Guardian nicht gefunden: {original_id}")
        else:
            if any(item.get("id") == check.get("id") for item in checks):
                raise ValueError(f"Check-ID bereits vorhanden: {check['id']}")
            checks.append(check)

        self.save(config)

    def delete_check(self, check_id: str):
        config = self.load()
        checks = config.get("checks", [])
        new_checks = [item for item in checks if item.get("id") != check_id]

        if len(new_checks) == len(checks):
            raise ValueError(f"Guardian nicht gefunden: {check_id}")

        config["checks"] = new_checks
        self.save(config)

    def toggle_check(self, check_id: str):
        config = self.load()
        for check in config.get("checks", []):
            if check.get("id") == check_id:
                check["enabled"] = not check.get("enabled", True)
                self.save(config)
                return
        raise ValueError(f"Guardian nicht gefunden: {check_id}")

    def duplicate_check(self, check_id: str):
        config = self.load()
        for check in config.get("checks", []):
            if check.get("id") == check_id:
                duplicate = copy.deepcopy(check)
                base_id = f"{check_id}_copy"
                candidate = base_id
                counter = 2
                existing_ids = {item.get("id") for item in config.get("checks", [])}
                while candidate in existing_ids:
                    candidate = f"{base_id}_{counter}"
                    counter += 1

                duplicate["id"] = candidate
                duplicate["device_id"] = candidate
                duplicate["name"] = f"{check.get('name', check_id)} Kopie"
                config["checks"].append(duplicate)
                self.save(config)
                return candidate

        raise ValueError(f"Guardian nicht gefunden: {check_id}")
