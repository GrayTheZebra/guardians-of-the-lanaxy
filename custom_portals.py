import ast
import copy
import importlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

from portals.base import BasePortal

CUSTOM_PORTAL_DIR = Path("/etc/lanaxy/portals.d")
SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def ensure_custom_dir():
    CUSTOM_PORTAL_DIR.mkdir(parents=True, exist_ok=True)
    return CUSTOM_PORTAL_DIR


def validate_module_name(name):
    normalized = str(name or "").removesuffix(".py")
    if not SAFE_NAME.fullmatch(normalized):
        raise ValueError("Ungültiger Portal-Modulname.")
    return normalized


def custom_path(module_name):
    return ensure_custom_dir() / f"{validate_module_name(module_name)}.py"


def load_custom_module(module_name):
    module_name = validate_module_name(module_name)
    path = custom_path(module_name)
    if not path.is_file():
        raise FileNotFoundError(f"Custom Portal nicht gefunden: {module_name}")
    import_name = f"lanaxy_custom_portals.{module_name}"
    spec = importlib.util.spec_from_file_location(import_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Custom Portal kann nicht geladen werden: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[import_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_portal_class(portal_type):
    if portal_type.startswith("custom:"):
        module = load_custom_module(portal_type.split(":", 1)[1])
    else:
        module = importlib.import_module(f"portals.{portal_type}")
    cls = getattr(module, "Portal", None)
    if cls is None or not issubclass(cls, BasePortal):
        raise ValueError("Portal-Modul enthält keine gültige Klasse 'Portal'.")
    return cls


def discover_portals():
    result = []
    builtin_dir = Path(__file__).parent / "portals"
    for path in sorted(builtin_dir.glob("*.py")):
        if path.name in {"__init__.py", "base.py"}:
            continue
        cls = importlib.import_module(f"portals.{path.stem}").Portal
        item = copy.deepcopy(cls.PORTAL)
        item.update({
            "module": path.stem,
            "file_module": path.stem,
            "schema": copy.deepcopy(cls.CONFIG_SCHEMA),
            "source": "builtin",
            "status": "loaded",
        })
        result.append(item)

    for path in sorted(ensure_custom_dir().glob("*.py")):
        item = {
            "module": f"custom:{path.stem}",
            "file_module": path.stem,
            "source": "custom",
            "status": "loaded",
            "error": "",
        }
        try:
            cls = load_custom_module(path.stem).Portal
            item.update(copy.deepcopy(cls.PORTAL))
            item["schema"] = copy.deepcopy(cls.CONFIG_SCHEMA)
        except Exception as error:
            item.update({
                "status": "failed",
                "error": str(error),
                "name": path.stem,
                "description": "Portal konnte nicht geladen werden.",
            })
        result.append(item)
    return sorted(result, key=lambda item: item.get("name", item["module"]))


def validate_source(source, module_name):
    validate_module_name(module_name)
    try:
        ast.parse(source, filename=f"{module_name}.py")
    except SyntaxError as error:
        raise ValueError(f"Syntaxfehler in Zeile {error.lineno}: {error.msg}") from error
    temporary = custom_path(module_name).with_name(f".{module_name}_validate.py")
    temporary.write_text(source, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(
            f"lanaxy_custom_portal_validate.{module_name}",
            temporary,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, "Portal", None)
        if cls is None or not issubclass(cls, BasePortal):
            raise ValueError("Portal muss von BasePortal erben.")
        if not isinstance(cls.PORTAL, dict) or not cls.PORTAL.get("id"):
            raise ValueError("PORTAL-Metadaten sind ungültig.")
        if not isinstance(cls.CONFIG_SCHEMA, dict):
            raise ValueError("CONFIG_SCHEMA muss ein Dictionary sein.")
        return copy.deepcopy(cls.PORTAL)
    finally:
        temporary.unlink(missing_ok=True)


def install_source(source, module_name, overwrite=False):
    metadata = validate_source(source, module_name)
    path = custom_path(module_name)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Custom Portal '{module_name}' existiert bereits.")
    temporary = path.with_suffix(".py.tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.chmod(0o640)
    temporary.replace(path)
    return metadata


def delete_custom_portal(module_name):
    path = custom_path(module_name)
    if not path.exists():
        raise FileNotFoundError(f"Custom Portal nicht gefunden: {module_name}")
    path.unlink()
    shutil.rmtree(path.with_suffix(""), ignore_errors=True)


def portal_template(module_name="mein_portal"):
    module_name = validate_module_name(module_name)
    return """from portals.base import BasePortal


class Portal(BasePortal):
    PORTAL = {
        "id": "%s",
        "name": "Mein Portal",
        "version": "1.0.0",
        "author": "Dein Name",
        "description": "Empfängt externe LANaxy-Befehle.",
        "icon": "portal",
        "category": "Benutzerdefiniert",
    }

    CONFIG_SCHEMA = {
        "name": {
            "label": "Name",
            "type": "text",
            "required": True,
        },
    }

    REQUIRED = ("name",)
    BACKGROUND = True

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
""" % module_name
