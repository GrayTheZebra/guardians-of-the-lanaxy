import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).parent
TRANSLATION_DIR = BASE_DIR / "translations"
SUPPORTED_LANGUAGES = {
    "de": "Deutsch",
    "en": "English",
}
DEFAULT_LANGUAGE = "en"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def nested_get(data: dict, key: str, default=None):
    value: Any = data
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def resolve_language(config: dict, request=None, session=None) -> str:
    configured = (
        config.get("web", {})
        .get("language", "auto")
    )

    if configured in SUPPORTED_LANGUAGES:
        return configured

    if session is not None:
        session_language = session.get("language")
        if session_language in SUPPORTED_LANGUAGES:
            return session_language

    if request is not None:
        best = request.accept_languages.best_match(
            list(SUPPORTED_LANGUAGES),
        )
        if best:
            return best

    return DEFAULT_LANGUAGE


def system_translations(language: str) -> dict:
    requested = load_json(
        TRANSLATION_DIR / "system" / f"{language}.json"
    )
    fallback = load_json(
        TRANSLATION_DIR / "system" / f"{DEFAULT_LANGUAGE}.json"
    )

    merged = dict(fallback)
    merged.update(requested)
    return merged


def translate(language: str, key: str, default=None, **values) -> str:
    translations = system_translations(language)
    text = nested_get(translations, key)

    if text is None:
        text = default if default is not None else key

    if not isinstance(text, str):
        return str(text)

    try:
        return text.format(**values)
    except (KeyError, ValueError):
        return text


def plugin_translation_paths(
    plugin_type: str,
    module_name: str,
    custom_path: Path | None = None,
) -> list[Path]:
    clean_name = module_name.split(":", 1)[-1]
    paths = []

    if custom_path is not None:
        paths.append(
            custom_path.with_suffix("")
            / "translations"
            / "{language}.json"
        )
        paths.append(custom_path.with_suffix("") / "{language}.json")

    paths.append(
        TRANSLATION_DIR
        / plugin_type
        / clean_name
        / "{language}.json"
    )
    return paths


def load_plugin_translation(
    plugin_type: str,
    module_name: str,
    language: str,
    custom_path: Path | None = None,
) -> dict:
    result = {}

    for template in plugin_translation_paths(
        plugin_type,
        module_name,
        custom_path,
    ):
        fallback_path = Path(
            str(template).format(language=DEFAULT_LANGUAGE)
        )
        requested_path = Path(
            str(template).format(language=language)
        )
        result.update(load_json(fallback_path))
        result.update(load_json(requested_path))

    return result


def localize_plugin(
    metadata: dict,
    plugin_type: str,
    module_name: str,
    language: str,
    custom_path: Path | None = None,
) -> dict:
    localized = {
        **metadata,
        "schema": {
            key: dict(value)
            for key, value in metadata.get("schema", {}).items()
        },
    }

    translations = load_plugin_translation(
        plugin_type,
        module_name,
        language,
        custom_path,
    )

    localized["name"] = translations.get(
        "name",
        localized.get("name", module_name),
    )
    localized["description"] = translations.get(
        "description",
        localized.get("description", ""),
    )
    localized["category"] = translations.get(
        "category",
        localized.get("category", ""),
    )

    fields = translations.get("fields", {})
    for key, field in localized["schema"].items():
        field_translation = fields.get(key, {})
        if isinstance(field_translation, dict):
            field["label"] = field_translation.get(
                "label",
                field.get("label", key),
            )
            if "help" in field_translation:
                field["help"] = field_translation["help"]

            translated_options = field_translation.get("options")
            if isinstance(translated_options, dict):
                field["option_labels"] = translated_options

    localized["messages"] = translations.get("messages", {})
    return localized


def save_plugin_translation(
    plugin_file: Path,
    language: str,
    content: str,
) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")

    content = content.strip()
    if not content:
        return

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid {language} translation JSON in line "
            f"{error.lineno}: {error.msg}"
        ) from error

    if not isinstance(parsed, dict):
        raise ValueError(
            f"The {language} translation must contain a JSON object."
        )

    directory = plugin_file.with_suffix("")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{language}.json"
    target.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
