from __future__ import annotations

import importlib
import py_compile
import sqlite3
import tempfile
from pathlib import Path

import yaml


REQUIRED_FILES = (
    "lanaxy.py",
    "web/app.py",
    "web/run.py",
    "database.py",
    "maintenance.py",
    "notifications.py",
    "miniguard_manager.py",
    "inventory_intelligence.py",
    "assistant_planner.py",
)

REQUIRED_IMPORTS = (
    "inventory_intelligence",
    "assistant_planner",
    "miniguard_manager",
    "maintenance",
    "notifications",
    "guardians.miniguard_inventory",
    "web.app",
)


def validate_project(project_dir: str | Path, config_path: str | Path = "/etc/lanaxy/config.yaml") -> list[str]:
    project = Path(project_dir)
    errors: list[str] = []

    for relative in REQUIRED_FILES:
        path = project / relative
        if not path.is_file():
            errors.append(f"Pflichtdatei fehlt: {relative}")

    for path in project.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as error:
            errors.append(f"Python-Syntaxfehler in {path.relative_to(project)}: {error}")

    config_file = Path(config_path)
    if config_file.exists():
        try:
            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("Konfiguration ist kein Objekt.")
            if not isinstance(config.get("checks", []), list):
                raise ValueError("checks ist keine Liste.")
            if not isinstance(config.get("notifications", {}), dict):
                raise ValueError("notifications ist kein Objekt.")
        except Exception as error:
            errors.append(f"Konfiguration ungültig: {error}")

    previous = list(__import__("sys").path)
    try:
        __import__("sys").path.insert(0, str(project))
        for module_name in REQUIRED_IMPORTS:
            try:
                importlib.import_module(module_name)
            except Exception as error:
                errors.append(f"Import {module_name} fehlgeschlagen: {error}")
    finally:
        __import__("sys").path[:] = previous

    return errors


def database_smoke_test(database_module) -> list[str]:
    errors: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="lanaxy-db-test-") as temporary:
            path = Path(temporary) / "test.db"
            db = database_module.Database(str(path))
            # Constructor/migrations are the important smoke test.
            with sqlite3.connect(path) as connection:
                connection.execute("SELECT 1").fetchone()
    except Exception as error:
        errors.append(f"Datenbanktest fehlgeschlagen: {error}")
    return errors
