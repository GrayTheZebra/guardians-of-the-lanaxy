import io
import json
import re
import zipfile
from pathlib import Path


PACKAGE_FORMAT = 1
SUPPORTED_TYPES = {"guardian", "beacon", "portal"}
SUPPORTED_LANGUAGES = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
SAFE_MODULE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_PACKAGE_SIZE = 2 * 1024 * 1024
MAX_MEMBER_SIZE = 512 * 1024
MAX_MEMBERS = 50


def safe_module(value):
    value = str(value or "").removesuffix(".py").strip()
    if not SAFE_MODULE.fullmatch(value):
        raise ValueError(
            "Der Modulname darf nur Kleinbuchstaben, Zahlen und _ "
            "enthalten und muss mit einem Buchstaben beginnen."
        )
    return value


def entrypoint_for(plugin_type):
    if plugin_type == "guardian":
        return "guardian.py"
    if plugin_type == "beacon":
        return "beacon.py"
    if plugin_type == "portal":
        return "portal.py"
    raise ValueError(f"Unbekannter Plugin-Typ: {plugin_type}")


def default_manifest(plugin_type, module_name):
    module_name = safe_module(module_name)
    return {
        "format": PACKAGE_FORMAT,
        "type": plugin_type,
        "module": module_name,
        "entrypoint": entrypoint_for(plugin_type),
        "name": {
            "guardian": "Mein Guardian",
            "beacon": "Mein Beacon",
            "portal": "Mein Portal",
        }[plugin_type],
        "version": "1.0.0",
        "author": "Dein Name",
        "minimum_lanaxy_version": "1.7.0",
    }


def default_readme(plugin_type, module_name):
    title = {
        "guardian": "Guardian",
        "beacon": "Beacon",
        "portal": "Portal",
    }[plugin_type]
    return f"""# Mein {title}

Dieses Paket enthält einen benutzerdefinierten LANaxy-{title}.

## Dateien

- `manifest.json`: Paketinformationen
- `{entrypoint_for(plugin_type)}`: Python-Quellcode
- `translations/de.json`: deutsche Texte
- `translations/en.json`: englische Texte

## Installation

Das ZIP unter LANaxy bei den {title}-Typen importieren.
"""


def default_translation(plugin_type, language):
    noun = {
        "guardian": "Guardian",
        "beacon": "Beacon",
        "portal": "Portal",
    }[plugin_type]
    if language == "de":
        return {
            "name": f"Mein {noun}",
            "description": f"Deutsche Beschreibung für den {noun}.",
            "fields": {},
            "messages": {},
        }
    return {
        "name": f"My {noun}",
        "description": f"English description for the {noun}.",
        "fields": {},
        "messages": {},
    }


def validate_manifest(manifest, expected_type=None):
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json muss ein JSON-Objekt enthalten.")
    if int(manifest.get("format", 0)) != PACKAGE_FORMAT:
        raise ValueError("Nicht unterstütztes Plugin-Paketformat.")
    plugin_type = manifest.get("type")
    if plugin_type not in SUPPORTED_TYPES:
        raise ValueError("manifest.json enthält einen ungültigen Plugin-Typ.")
    if expected_type and plugin_type != expected_type:
        raise ValueError(
            f"Dieses Paket ist ein {plugin_type}-Paket, erwartet wurde "
            f"{expected_type}."
        )
    module_name = safe_module(manifest.get("module"))
    expected_entrypoint = entrypoint_for(plugin_type)
    if manifest.get("entrypoint") != expected_entrypoint:
        raise ValueError(
            f"Der Entrypoint muss '{expected_entrypoint}' heißen."
        )
    for key in ("name", "version", "author"):
        if not str(manifest.get(key, "")).strip():
            raise ValueError(f"manifest.json benötigt das Feld '{key}'.")
    manifest = dict(manifest)
    manifest["module"] = module_name
    return manifest


def _normalize_members(archive):
    files = {}
    members = [
        member
        for member in archive.infolist()
        if not member.is_dir()
    ]
    if len(members) > MAX_MEMBERS:
        raise ValueError("Das Plugin-Paket enthält zu viele Dateien.")

    for member in members:
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsicherer ZIP-Pfad: {member.filename}")
        if member.file_size > MAX_MEMBER_SIZE:
            raise ValueError(f"Datei ist zu groß: {member.filename}")
        files[member.filename.strip("/")] = archive.read(member)

    # Accept packages wrapped in one top-level folder.
    if "manifest.json" not in files:
        roots = {
            name.split("/", 1)[0]
            for name in files
            if "/" in name
        }
        if len(roots) == 1:
            root = next(iter(roots)) + "/"
            files = {
                name[len(root):]: data
                for name, data in files.items()
                if name.startswith(root)
            }
    return files


def parse_package_bytes(data, expected_type=None):
    if len(data) > MAX_PACKAGE_SIZE:
        raise ValueError("Das Plugin-Paket ist größer als 2 MB.")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = _normalize_members(archive)
    except zipfile.BadZipFile as error:
        raise ValueError("Die Datei ist kein gültiges ZIP-Paket.") from error

    if "manifest.json" not in files:
        raise ValueError("manifest.json fehlt im Plugin-Paket.")

    try:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("manifest.json ist ungültig.") from error

    manifest = validate_manifest(manifest, expected_type)
    entrypoint = manifest["entrypoint"]
    if entrypoint not in files:
        raise ValueError(f"{entrypoint} fehlt im Plugin-Paket.")

    try:
        source = files[entrypoint].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{entrypoint} ist nicht UTF-8-codiert.") from error

    translations = {}
    for name, raw in files.items():
        if not name.startswith("translations/") or not name.endswith(".json"):
            continue
        language = Path(name).stem
        if not SUPPORTED_LANGUAGES.fullmatch(language):
            raise ValueError(f"Ungültiger Sprachcode: {language}")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Ungültige Sprachdatei: {name}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{name} muss ein JSON-Objekt enthalten.")
        translations[language] = value

    readme = files.get("README.md", b"").decode("utf-8", errors="replace")
    return {
        "manifest": manifest,
        "source": source,
        "translations": translations,
        "readme": readme,
    }


def build_package_bytes(
    plugin_type,
    module_name,
    source,
    translations=None,
    manifest=None,
    readme="",
):
    module_name = safe_module(module_name)
    manifest = validate_manifest(
        manifest or default_manifest(plugin_type, module_name),
        plugin_type,
    )
    manifest["module"] = module_name
    manifest["entrypoint"] = entrypoint_for(plugin_type)

    memory = io.BytesIO()
    with zipfile.ZipFile(
        memory,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        archive.writestr(manifest["entrypoint"], source)
        archive.writestr(
            "README.md",
            readme or default_readme(plugin_type, module_name),
        )
        for language, value in sorted((translations or {}).items()):
            if not SUPPORTED_LANGUAGES.fullmatch(language):
                raise ValueError(f"Ungültiger Sprachcode: {language}")
            if isinstance(value, str):
                value = json.loads(value)
            if not isinstance(value, dict):
                raise ValueError(
                    f"Übersetzung {language} muss ein JSON-Objekt sein."
                )
            archive.writestr(
                f"translations/{language}.json",
                json.dumps(value, ensure_ascii=False, indent=2),
            )
    memory.seek(0)
    return memory


def template_package(plugin_type, module_name, source):
    manifest = default_manifest(plugin_type, module_name)
    return build_package_bytes(
        plugin_type,
        module_name,
        source,
        translations={
            "de": default_translation(plugin_type, "de"),
            "en": default_translation(plugin_type, "en"),
        },
        manifest=manifest,
        readme=default_readme(plugin_type, module_name),
    )


def package_metadata_for_storage(plugin_file):
    plugin_file = Path(plugin_file)
    metadata_dir = plugin_file.with_suffix("")
    manifest_path = metadata_dir / "manifest.json"
    readme_path = metadata_dir / "README.md"
    translations_dir = metadata_dir / "translations"

    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception:
            manifest = {}

    translations = {}
    if translations_dir.exists():
        for path in translations_dir.glob("*.json"):
            try:
                translations[path.stem] = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except Exception:
                continue

    # Compatibility with v1.4/v1.5 language storage.
    for path in metadata_dir.glob("*.json"):
        if path.name == "manifest.json":
            continue
        try:
            translations.setdefault(
                path.stem,
                json.loads(path.read_text(encoding="utf-8")),
            )
        except Exception:
            continue

    readme = (
        readme_path.read_text(encoding="utf-8")
        if readme_path.exists()
        else ""
    )
    return manifest, translations, readme


def save_package_metadata(
    plugin_file,
    manifest,
    translations,
    readme,
):
    plugin_file = Path(plugin_file)
    metadata_dir = plugin_file.with_suffix("")
    translations_dir = metadata_dir / "translations"
    translations_dir.mkdir(parents=True, exist_ok=True)

    (metadata_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (metadata_dir / "README.md").write_text(
        readme or "",
        encoding="utf-8",
    )

    for old in translations_dir.glob("*.json"):
        old.unlink()
    for language, value in translations.items():
        (translations_dir / f"{language}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
