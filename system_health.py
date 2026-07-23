from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maintenance import list_backups
from miniguard_compat import evaluate_agent


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except ValueError:
        return None


def database_healthy(path: str | Path) -> tuple[bool, str]:
    path = Path(path)
    if not path.exists():
        return False, "Datenbankdatei fehlt."
    try:
        with sqlite3.connect(path, timeout=5) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            return False, f"SQLite quick_check: {result[0] if result else 'kein Ergebnis'}"
        return True, "SQLite quick_check erfolgreich."
    except Exception as error:
        return False, str(error)


def build_health(
    *,
    app_version: str,
    config: dict[str, Any],
    runtime: dict[str, Any],
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    monitoring_running: bool,
    web_running: bool,
) -> dict[str, Any]:
    database_path = config.get("lanaxy", {}).get("database_file", "/var/lib/lanaxy/lanaxy.db")
    db_ok, db_message = database_healthy(database_path)
    active_checks = [check for check in config.get("checks", []) if check.get("enabled", True)]
    problems = sum(
        1 for check in active_checks
        if int(state.get(check.get("id"), {}).get("level", 0) or 0) > 0
    )
    incompatible_agents = []
    offline_agents = []
    for agent in agents:
        if not agent.get("registered") or not agent.get("enabled", True):
            continue
        compatibility = evaluate_agent(agent, app_version)
        if not compatibility.get("compatible"):
            incompatible_agents.append(agent.get("name") or agent.get("id"))
        age = _age_seconds(agent.get("last_seen"))
        if age is None or age > 180:
            offline_agents.append(agent.get("name") or agent.get("id"))

    try:
        backups = list_backups()
        backup_error = ""
    except Exception as error:
        backups = []
        backup_error = str(error)
    last_backup_raw = backups[0] if backups else None
    last_backup = None
    if last_backup_raw:
        last_backup = {
            "name": str(last_backup_raw.get("name") or ""),
            "size": int(last_backup_raw.get("size", 0) or 0),
            "size_human": str(last_backup_raw.get("size_human") or ""),
            "modified": str(last_backup_raw.get("modified") or ""),
            "created_at": str(last_backup_raw.get("created_at") or ""),
            "includes_database": last_backup_raw.get("includes_database"),
            "reason": str(last_backup_raw.get("reason") or ""),
            "invalid": bool(last_backup_raw.get("invalid", False)),
        }
    backup_age = _age_seconds((last_backup or {}).get("created_at") or (last_backup or {}).get("modified"))
    backup_ok = bool(last_backup and backup_age is not None and backup_age <= 14 * 86400)

    checks = [
        {"id": "monitoring", "label": "Monitoring-Dienst", "ok": monitoring_running, "message": "aktiv" if monitoring_running else "nicht aktiv"},
        {"id": "web", "label": "Webdienst", "ok": web_running, "message": "aktiv" if web_running else "nicht aktiv"},
        {"id": "database", "label": "Datenbank", "ok": db_ok, "message": db_message},
        {"id": "backup", "label": "Backup", "ok": backup_ok, "message": (
            f"letztes Backup vor {int(backup_age // 86400)} Tagen"
            if backup_age is not None
            else (f"Backup-Verzeichnis nicht lesbar: {backup_error}" if backup_error else "kein Backup vorhanden")
        )},
        {"id": "miniguards", "label": "MiniGuards", "ok": not incompatible_agents and not offline_agents, "message": (
            "alle einsatzbereit" if not incompatible_agents and not offline_agents
            else f"{len(offline_agents)} offline, {len(incompatible_agents)} inkompatibel"
        )},
    ]
    healthy = all(item["ok"] for item in checks[:3])
    ready = all(item["ok"] for item in checks)
    return {
        "status": "ok" if healthy else "critical",
        "readiness": "ready" if ready else "warning",
        "version": app_version,
        "monitoring": monitoring_running,
        "web": web_running,
        "mqtt": bool(runtime.get("mqtt_connected")),
        "database": {"ok": db_ok, "message": db_message, "path": str(database_path)},
        "backup": {"ok": backup_ok, "last": last_backup, "age_seconds": backup_age},
        "miniguards": {
            "total": len([a for a in agents if a.get("registered")]),
            "offline": offline_agents,
            "incompatible": incompatible_agents,
        },
        "uptime_seconds": int(runtime.get("uptime_seconds", 0) or 0),
        "guardians": len(active_checks),
        "problems": problems,
        "last_loop": runtime.get("last_loop", ""),
        "last_reload": runtime.get("last_reload", ""),
        "checks": checks,
    }
