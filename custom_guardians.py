import ast
import importlib.util
import re
import shutil
import sys
from pathlib import Path

from guardians.base import BaseGuardian


CUSTOM_GUARDIAN_DIR = Path("/etc/lanaxy/guardians.d")
SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def ensure_custom_dir():
    CUSTOM_GUARDIAN_DIR.mkdir(parents=True, exist_ok=True)
    return CUSTOM_GUARDIAN_DIR


def validate_module_name(name):
    normalized = name.removesuffix(".py")
    if not SAFE_NAME.fullmatch(normalized):
        raise ValueError(
            "Der Dateiname darf nur Kleinbuchstaben, Zahlen und _ enthalten "
            "und muss mit einem Buchstaben beginnen."
        )
    return normalized


def custom_path(module_name):
    return ensure_custom_dir() / f"{validate_module_name(module_name)}.py"


def load_custom_module(module_name):
    module_name = validate_module_name(module_name)
    path = custom_path(module_name)
    if not path.is_file():
        raise FileNotFoundError(f"Custom Guardian nicht gefunden: {module_name}")

    import_name = f"lanaxy_custom_guardians.{module_name}"
    spec = importlib.util.spec_from_file_location(import_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Custom Guardian kann nicht geladen werden: {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[import_name] = module
    spec.loader.exec_module(module)
    return module


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
            f"lanaxy_custom_validate.{module_name}",
            temporary,
        )
        if spec is None or spec.loader is None:
            raise ValueError("Guardian-Modul konnte nicht vorbereitet werden.")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        guardian_class = getattr(module, "Guardian", None)

        if guardian_class is None:
            raise ValueError("Die Klasse 'Guardian' fehlt.")
        if not issubclass(guardian_class, BaseGuardian):
            raise ValueError("Guardian muss von BaseGuardian erben.")

        metadata = getattr(guardian_class, "GUARDIAN", None)
        schema = getattr(guardian_class, "CONFIG_SCHEMA", None)

        if not isinstance(metadata, dict):
            raise ValueError("GUARDIAN muss ein Dictionary sein.")
        if not metadata.get("id") or not metadata.get("name"):
            raise ValueError("GUARDIAN benötigt mindestens 'id' und 'name'.")
        if not isinstance(schema, dict):
            raise ValueError("CONFIG_SCHEMA muss ein Dictionary sein.")

        return {
            "id": metadata.get("id"),
            "name": metadata.get("name"),
            "version": metadata.get("version", "0.0.0"),
            "description": metadata.get("description", ""),
            "schema_fields": len(schema),
        }
    finally:
        temporary.unlink(missing_ok=True)


def install_source(source, module_name, overwrite=False):
    metadata = validate_source(source, module_name)
    path = custom_path(module_name)

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Custom Guardian '{module_name}' existiert bereits."
        )

    temporary = path.with_suffix(".py.tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.chmod(0o640)
    temporary.replace(path)
    return metadata


def list_custom_guardians():
    ensure_custom_dir()
    result = []

    for path in sorted(CUSTOM_GUARDIAN_DIR.glob("*.py")):
        item = {
            "module": path.stem,
            "path": str(path),
            "size": path.stat().st_size,
            "status": "loaded",
            "error": "",
        }

        try:
            module = load_custom_module(path.stem)
            guardian_class = module.Guardian
            item.update(guardian_class.GUARDIAN)
            item["schema_fields"] = len(
                getattr(guardian_class, "CONFIG_SCHEMA", {})
            )
        except Exception as error:
            item["status"] = "failed"
            item["error"] = str(error)

        result.append(item)

    return result


def delete_custom_guardian(module_name):
    path = custom_path(module_name)
    if not path.exists():
        raise FileNotFoundError(f"Custom Guardian nicht gefunden: {module_name}")
    path.unlink()
    shutil.rmtree(path.with_suffix(""), ignore_errors=True)



def guardian_template(module_name="mein_guardian"):
    module_name = validate_module_name(module_name)

    return f"""from guardians.base import BaseGuardian
from utils.network import ping


class Guardian(BaseGuardian):
    GUARDIAN = {{
        "id": "{module_name}",
        "name": "Mein Guardian",
        "version": "1.0.0",
        "author": "Dein Name",
        "description": "Überwacht ein eigenes Gerät.",
        "icon": "network",
        "category": "Benutzerdefiniert",
    }}

    CONFIG_SCHEMA = {{
        "name": {{
            "type": "text",
            "label": "Name",
            "required": True,
        }},
        "id": {{
            "type": "slug",
            "label": "Guardian-ID",
        }},
        "device_id": {{
            "type": "hidden",
            "label": "Geräte-ID",
        }},
        "interval": {{
            "type": "number",
            "label": "Intervall (Sekunden)",
            "default": 30,
            "min": 2,
        }},
        "timeout": {{
            "type": "number",
            "label": "Timeout (Sekunden)",
            "default": 3,
            "min": 1,
        }},
        "retries": {{
            "type": "number",
            "label": "Fehlversuche bis Critical",
            "default": 3,
            "min": 1,
        }},
        "host": {{
            "type": "text",
            "label": "Host oder IP",
            "required": True,
        }},
    }}

    REQUIRED = ("host",)

    def run(self):
        result = ping(
            self.check["host"],
            self.timeout,
        )

        if not result["ok"]:
            return self.critical(
                "Gerät ist nicht erreichbar",
                response_time=int(result["ms"]),
                details={{
                    "ping": result,
                }},
            )

        return self.ok(
            "Gerät ist erreichbar",
            response_time=int(result["ms"]),
            details={{
                "ping": result,
            }},
        )
"""
