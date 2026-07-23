import json
import shlex
from typing import Any


COMMAND_ALIASES = {
    "run": "run_guardian",
    "check": "run_guardian",
    "status": "get_status",
    "runtime": "get_runtime",
    "maintenance": "maintenance",
    "endmaintenance": "end_maintenance",
    "mute": "mute",
    "unmute": "unmute",
    "testbeacon": "test_beacon",
    "pauserule": "pause_rule",
    "resumerule": "resume_rule",
    "incidents": "get_incidents",
    "ack": "acknowledge",
    "unack": "unacknowledge",
    "mutebeacon": "mute_beacon",
    "unmutebeacon": "unmute_beacon",
}

HELP_TEXT = """Verfügbare Befehle:
/run GUARDIAN_ID – Guardian sofort prüfen
/status [GUARDIAN_ID] – Status abrufen
/runtime – Laufzeitzustand abrufen
/maintenance GUARDIAN_ID [MINUTEN] – Wartung starten
/endmaintenance GUARDIAN_ID – Wartung beenden
/testbeacon BEACON_ID – Beacon testen
/pauserule RULE_ID [MINUTEN] – Rule pausieren
/resumerule RULE_ID – Rule fortsetzen
/incidents [GUARDIAN_ID] – Incidents abrufen
/help – diese Übersicht"""


def allowed(config: dict[str, Any], command: str) -> bool:
    configured = str(config.get("allowed_commands", "*")).strip()
    if configured == "*":
        return True
    return command in {
        item.strip()
        for item in configured.split(",")
        if item.strip()
    }


def parse_chat_command(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parts = shlex.split(str(text or "").strip())
    except ValueError as error:
        return None, f"Befehl konnte nicht gelesen werden: {error}"
    if not parts:
        return None, None
    command_name = parts[0].lstrip("/!").split("@", 1)[0].lower()
    if command_name in {"help", "hilfe", "start"}:
        return None, HELP_TEXT
    command = COMMAND_ALIASES.get(command_name, command_name)
    payload: dict[str, Any] = {"command": command}
    args = parts[1:]

    target_commands = {
        "run_guardian", "get_status", "maintenance", "end_maintenance",
        "test_beacon", "pause_rule", "resume_rule", "mute_beacon",
        "unmute_beacon",
    }
    if command in target_commands and args:
        payload["target"] = args.pop(0)
    if command in {"maintenance", "pause_rule"} and args:
        try:
            payload["duration_minutes"] = int(args.pop(0))
        except ValueError:
            return None, "Die Dauer muss als Anzahl Minuten angegeben werden."
    if command == "get_incidents" and args:
        payload["target"] = args.pop(0)
    if command in {"acknowledge", "unacknowledge"} and args:
        payload["incident_id"] = args.pop(0)
    if args:
        payload["reason"] = " ".join(args)
    return payload, None


def format_result(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"
    command = result.get("command", "Befehl")
    if command == "run_guardian":
        guardian_result = result.get("result") or {}
        status = guardian_result.get("status", guardian_result.get("level", "ausgeführt"))
        message = guardian_result.get("message", "")
        return f"Guardian {result.get('target', '')}: {status}" + (f"\n{message}" if message else "")
    if command == "get_status":
        data = result.get("status", result.get("result", result))
        return _compact_json(data)
    if command == "get_incidents":
        return _compact_json(result.get("incidents", result))
    return f"{command}: erfolgreich" + (f" ({result.get('target')})" if result.get("target") else "")


def _compact_json(value: Any, limit: int = 1800) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[: limit - 24] + "\n… Ausgabe gekürzt"
