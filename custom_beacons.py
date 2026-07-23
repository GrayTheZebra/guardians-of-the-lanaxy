import ast
import copy
import importlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

from beacons.base import BaseBeacon


CUSTOM_BEACON_DIR = Path("/etc/lanaxy/beacons.d")
SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def ensure_custom_dir():
    CUSTOM_BEACON_DIR.mkdir(parents=True, exist_ok=True)
    return CUSTOM_BEACON_DIR


def validate_module_name(name):
    normalized = name.removesuffix(".py")
    if not SAFE_NAME.fullmatch(normalized):
        raise ValueError(
            "Der Modulname darf nur Kleinbuchstaben, Zahlen und _ enthalten "
            "und muss mit einem Buchstaben beginnen."
        )
    return normalized


def custom_path(module_name):
    return ensure_custom_dir() / f"{validate_module_name(module_name)}.py"


def load_custom_module(module_name):
    module_name = validate_module_name(module_name)
    path = custom_path(module_name)
    if not path.is_file():
        raise FileNotFoundError(f"Custom Beacon nicht gefunden: {module_name}")

    import_name = f"lanaxy_custom_beacons.{module_name}"
    spec = importlib.util.spec_from_file_location(import_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Custom Beacon kann nicht geladen werden: {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[import_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_beacon_class(beacon_type):
    if beacon_type.startswith("custom:"):
        module = load_custom_module(beacon_type.split(":", 1)[1])
    else:
        module = importlib.import_module(f"beacons.{beacon_type}")
    beacon_class = getattr(module, "Beacon", None)
    if beacon_class is None or not issubclass(beacon_class, BaseBeacon):
        raise ValueError("Beacon-Modul enthält keine gültige Klasse 'Beacon'.")
    return beacon_class


def discover_beacons():
    result = []
    builtin_dir = Path(__file__).parent / "beacons"

    for path in sorted(builtin_dir.glob("*.py")):
        if path.name in {"__init__.py", "base.py"}:
            continue
        module = importlib.import_module(f"beacons.{path.stem}")
        beacon_class = module.Beacon
        metadata = copy.deepcopy(beacon_class.BEACON)
        metadata["module"] = path.stem
        metadata["schema"] = copy.deepcopy(beacon_class.CONFIG_SCHEMA)
        metadata["source"] = "builtin"
        metadata["status"] = "loaded"
        result.append(metadata)

    for path in sorted(ensure_custom_dir().glob("*.py")):
        item = {
            "module": f"custom:{path.stem}",
            "file_module": path.stem,
            "source": "custom",
            "status": "loaded",
            "error": "",
        }
        try:
            module = load_custom_module(path.stem)
            beacon_class = module.Beacon
            item.update(copy.deepcopy(beacon_class.BEACON))
            item["schema"] = copy.deepcopy(beacon_class.CONFIG_SCHEMA)
        except Exception as error:
            item["status"] = "failed"
            item["error"] = str(error)
            item["name"] = path.stem
            item["description"] = "Beacon konnte nicht geladen werden."
        result.append(item)

    return sorted(result, key=lambda item: item.get("name", item["module"]))


def validate_source(source, module_name):
    validate_module_name(module_name)
    try:
        ast.parse(source, filename=f"{module_name}.py")
    except SyntaxError as error:
        raise ValueError(
            f"Syntaxfehler in Zeile {error.lineno}: {error.msg}"
        ) from error

    temporary = custom_path(module_name).with_name(f".{module_name}_validate.py")
    temporary.write_text(source, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(
            f"lanaxy_custom_beacon_validate.{module_name}",
            temporary,
        )
        if spec is None or spec.loader is None:
            raise ValueError("Beacon-Modul konnte nicht vorbereitet werden.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        beacon_class = getattr(module, "Beacon", None)
        if beacon_class is None or not issubclass(beacon_class, BaseBeacon):
            raise ValueError("Beacon muss von BaseBeacon erben.")
        if not isinstance(beacon_class.BEACON, dict):
            raise ValueError("BEACON muss ein Dictionary sein.")
        if not beacon_class.BEACON.get("id") or not beacon_class.BEACON.get("name"):
            raise ValueError("BEACON benötigt mindestens id und name.")
        if not isinstance(beacon_class.CONFIG_SCHEMA, dict):
            raise ValueError("CONFIG_SCHEMA muss ein Dictionary sein.")
        return copy.deepcopy(beacon_class.BEACON)
    finally:
        temporary.unlink(missing_ok=True)


def install_source(source, module_name, overwrite=False):
    metadata = validate_source(source, module_name)
    path = custom_path(module_name)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Custom Beacon '{module_name}' existiert bereits.")
    temporary = path.with_suffix(".py.tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.chmod(0o640)
    temporary.replace(path)
    return metadata


def delete_custom_beacon(module_name):
    path = custom_path(module_name)
    if not path.exists():
        raise FileNotFoundError(f"Custom Beacon nicht gefunden: {module_name}")
    path.unlink()
    shutil.rmtree(path.with_suffix(""), ignore_errors=True)


def beacon_template(module_name="mein_beacon"):
    module_name = validate_module_name(module_name)
    return f"""from beacons.base import BaseBeacon


class Beacon(BaseBeacon):
    BEACON = {{
        "id": "{module_name}",
        "name": "Mein Beacon",
        "version": "1.0.0",
        "author": "Dein Name",
        "description": "Sendet eine eigene Benachrichtigung.",
        "icon": "beacon",
        "category": "Benutzerdefiniert",
    }}

    CONFIG_SCHEMA = {{
        "name": {{
            "label": "Name",
            "type": "text",
            "required": True,
        }},
        "target": {{
            "label": "Ziel",
            "type": "text",
            "required": True,
        }},
        "api_key": {{
            "label": "API-Key",
            "type": "password",
            "secret": True,
        }},
        "timeout": {{
            "label": "Timeout (Sekunden)",
            "type": "number",
            "default": 10,
        }},
    }}

    REQUIRED = ("target",)

    def send(self, notification):
        # notification ist ein Dictionary, zum Beispiel:
        # notification["title"], notification["message"],
        # notification["kind"], notification["source"]
        #
        # Hier die eigene API ansprechen.
        print(
            f"{{notification['title']}} -> {{self.config['target']}}"
        )
"""
