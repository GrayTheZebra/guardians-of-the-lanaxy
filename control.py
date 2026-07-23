import copy
import json
import os
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from config import load_config
from guardian_manager import load_guardian


CONTROL_STATE_PATH = Path("/var/lib/lanaxy/control-state.json")
APP_STATE_PATH = Path("/var/lib/lanaxy/state.json")
AUDIT_LIMIT = 500


CONTROL_COMMANDS = {
    "mute": {
        "label": "Alle Meldungen stummschalten",
        "description": "Unterdrückt Benachrichtigungen global, optional nur für bestimmte Stufen und eine begrenzte Zeit.",
        "parameters": "Optional: levels, duration_minutes oder until, reason",
    },
    "unmute": {
        "label": "Globale Stummschaltung aufheben",
        "description": "Beendet die globale Stummschaltung sofort.",
        "parameters": "Keine zusätzlichen Angaben",
    },
    "maintenance": {
        "label": "Guardian in Wartung setzen",
        "description": "Versetzt einen Guardian zeitweise in den Wartungsmodus.",
        "parameters": "Erforderlich: target; optional: duration_minutes oder until, reason",
    },
    "end_maintenance": {
        "label": "Wartung beenden",
        "description": "Beendet den Wartungsmodus eines Guardians.",
        "parameters": "Erforderlich: target",
    },
    "run_guardian": {
        "label": "Guardian sofort ausführen",
        "description": "Startet die Prüfung eines Guardians unabhängig vom regulären Intervall.",
        "parameters": "Erforderlich: target",
    },
    "test_beacon": {
        "label": "Beacon testen",
        "description": "Sendet eine Testnachricht über den ausgewählten Beacon.",
        "parameters": "Erforderlich: target",
    },
    "pause_rule": {
        "label": "Rule pausieren",
        "description": "Pausiert eine Benachrichtigungs-Rule zeitweise oder unbegrenzt.",
        "parameters": "Erforderlich: target; optional: duration_minutes oder until, reason",
    },
    "resume_rule": {
        "label": "Rule fortsetzen",
        "description": "Hebt die Pause einer Rule auf.",
        "parameters": "Erforderlich: target",
    },
    "get_status": {
        "label": "Guardian-Status abrufen",
        "description": "Liefert den Status eines einzelnen Guardians oder aller Guardians.",
        "parameters": "Optional: target",
    },
    "get_runtime": {
        "label": "Runtime-Zustand abrufen",
        "description": "Liefert Wartungen, Pausen, Stummschaltungen und weitere Laufzeitzustände.",
        "parameters": "Keine zusätzlichen Angaben",
    },
    "acknowledge": {
        "label": "Incident bestätigen",
        "description": "Bestätigt einen Incident über seine ID oder den offenen Incident eines Guardians.",
        "parameters": "incident_id oder target; optional: actor, note",
    },
    "unacknowledge": {
        "label": "Incident-Bestätigung aufheben",
        "description": "Entfernt die Bestätigung eines Incidents.",
        "parameters": "Erforderlich: incident_id",
    },
    "get_incidents": {
        "label": "Incidents abrufen",
        "description": "Liefert eine gefilterte Liste gespeicherter Incidents.",
        "parameters": "Optional: status, target, limit",
    },
    "mute_beacon": {
        "label": "Beacon stummschalten",
        "description": "Unterdrückt Ausgaben eines bestimmten Beacons zeitweise oder unbegrenzt.",
        "parameters": "Erforderlich: target; optional: duration_minutes oder until, reason",
    },
    "unmute_beacon": {
        "label": "Beacon-Stummschaltung aufheben",
        "description": "Aktiviert einen zuvor stummgeschalteten Beacon wieder.",
        "parameters": "Erforderlich: target",
    },
}


def now():
    return datetime.now()


def iso(value=None):
    return (value or now()).isoformat(timespec="seconds")


def parse_until(value: str | None, duration_minutes=None):
    if duration_minutes not in (None, ""):
        return now() + timedelta(minutes=max(1, int(duration_minutes)))

    if not value:
        return None

    value = str(value).strip()
    if len(value) == 5 and ":" in value:
        hour, minute = (int(part) for part in value.split(":", 1))
        candidate = now().replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now():
            candidate += timedelta(days=1)
        return candidate

    parsed = datetime.fromisoformat(value)
    return parsed


def active_until(value):
    if not value:
        return True
    try:
        return now() < datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False


class ControlState:
    def __init__(self, path=CONTROL_STATE_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = self._load()

    def _default(self):
        return {
            "mute": {},
            "maintenance": {},
            "paused_rules": {},
            "acknowledged": {},
            "muted_beacons": {},
            "audit": [],
            "updated_at": iso(),
        }

    def _load(self):
        if not self.path.exists():
            return self._default()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return {**self._default(), **value}
        except Exception:
            pass
        return self._default()

    def reload(self):
        with self.lock:
            self.data = self._load()
            self.prune()
            return copy.deepcopy(self.data)

    def save(self):
        with self.lock:
            self.prune()
            self.data["updated_at"] = iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(temp, 0o600)
            temp.replace(self.path)

    def prune(self):
        for key in (
            "mute",
            "maintenance",
            "paused_rules",
            "acknowledged",
            "muted_beacons",
        ):
            section = self.data.setdefault(key, {})
            expired = [
                item_id
                for item_id, item in section.items()
                if isinstance(item, dict)
                and item.get("until")
                and not active_until(item.get("until"))
            ]
            for item_id in expired:
                section.pop(item_id, None)
        self.data["audit"] = self.data.get("audit", [])[-AUDIT_LIMIT:]

    def audit(self, command, source, ok, request_id="", details=None):
        self.data.setdefault("audit", []).append({
            "timestamp": iso(),
            "command": command,
            "source": source,
            "ok": bool(ok),
            "request_id": request_id or "",
            "details": details or {},
        })
        self.save()

    def snapshot(self):
        return self.reload()


def generate_control_token():
    token = secrets.token_urlsafe(36)
    return token, generate_password_hash(
        token,
        method="pbkdf2:sha256:600000",
    )


def verify_control_token(config, token):
    control = config.get("control", {})
    if not control.get("enabled"):
        return False
    token_hash = control.get("token_hash", "")
    return bool(token and token_hash and check_password_hash(token_hash, token))


def global_mute_active(state=None, level=None):
    state = state or ControlState().snapshot()
    mute = state.get("mute", {}).get("all")
    if not mute or not active_until(mute.get("until")):
        return False
    levels = mute.get("levels", [])
    return not levels or level in levels


def rule_paused(rule_id, state=None):
    state = state or ControlState().snapshot()
    item = state.get("paused_rules", {}).get(rule_id)
    return bool(item and active_until(item.get("until")))


def beacon_muted(beacon_id, state=None):
    state = state or ControlState().snapshot()
    item = state.get("muted_beacons", {}).get(beacon_id)
    return bool(item and active_until(item.get("until")))


def runtime_maintenance(check_id, state=None):
    state = state or ControlState().snapshot()
    item = state.get("maintenance", {}).get(check_id)
    if item and active_until(item.get("until")):
        return item
    return None


class ControlEngine:
    ALLOWED_COMMANDS = set(CONTROL_COMMANDS)

    def __init__(
        self,
        config_path="/etc/lanaxy/config.yaml",
        database=None,
    ):
        self.config_path = config_path
        self.database = database
        self.state = ControlState()

    def _config(self):
        return load_config(self.config_path)

    def _result(self, ok, command, request_id="", **values):
        return {
            "ok": bool(ok),
            "command": command,
            "request_id": request_id or "",
            "timestamp": iso(),
            **values,
        }

    def execute(self, payload, source="unknown"):
        if not isinstance(payload, dict):
            raise ValueError("Der Befehl muss ein JSON-Objekt sein.")

        command = str(payload.get("command", "")).strip()
        request_id = str(payload.get("request_id", "")).strip()

        if command not in self.ALLOWED_COMMANDS:
            result = self._result(
                False,
                command or "unknown",
                request_id,
                error="Unbekannter oder nicht erlaubter Befehl.",
            )
            self.state.audit(command, source, False, request_id, result)
            return result

        try:
            handler = getattr(self, f"_command_{command}")
            result = handler(payload, request_id)
            self.state.audit(command, source, True, request_id, result)
            return result
        except Exception as error:
            result = self._result(
                False,
                command,
                request_id,
                error=str(error),
            )
            self.state.audit(command, source, False, request_id, result)
            return result

    def _until(self, payload):
        parsed = parse_until(
            payload.get("until"),
            payload.get("duration_minutes"),
        )
        return iso(parsed) if parsed else ""

    def _command_mute(self, payload, request_id):
        levels = payload.get("levels", [])
        if isinstance(levels, str):
            levels = [levels]
        allowed = {"warning", "critical", "recovery"}
        levels = [value for value in levels if value in allowed]
        self.state.reload()
        self.state.data["mute"]["all"] = {
            "until": self._until(payload),
            "levels": levels,
            "reason": str(payload.get("reason", "")),
        }
        self.state.save()
        return self._result(
            True,
            "mute",
            request_id,
            scope="all",
            until=self.state.data["mute"]["all"]["until"],
            levels=levels,
        )

    def _command_unmute(self, payload, request_id):
        self.state.reload()
        self.state.data["mute"].pop("all", None)
        self.state.save()
        return self._result(True, "unmute", request_id, scope="all")

    def _command_maintenance(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        config = self._config()
        if not any(item.get("id") == target for item in config.get("checks", [])):
            raise ValueError(f"Guardian nicht gefunden: {target}")
        self.state.reload()
        self.state.data["maintenance"][target] = {
            "until": self._until(payload),
            "reason": str(payload.get("reason", "")),
        }
        self.state.save()
        return self._result(
            True,
            "maintenance",
            request_id,
            target=target,
            until=self.state.data["maintenance"][target]["until"],
        )

    def _command_end_maintenance(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        self.state.reload()
        self.state.data["maintenance"].pop(target, None)
        self.state.save()
        return self._result(
            True,
            "end_maintenance",
            request_id,
            target=target,
        )

    def _command_pause_rule(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        config = self._config()
        rules = config.get("notifications", {}).get("rules", [])
        if not any(item.get("id") == target for item in rules):
            raise ValueError(f"Rule nicht gefunden: {target}")
        self.state.reload()
        self.state.data["paused_rules"][target] = {
            "until": self._until(payload),
            "reason": str(payload.get("reason", "")),
        }
        self.state.save()
        return self._result(
            True,
            "pause_rule",
            request_id,
            target=target,
            until=self.state.data["paused_rules"][target]["until"],
        )

    def _command_resume_rule(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        self.state.reload()
        self.state.data["paused_rules"].pop(target, None)
        self.state.save()
        return self._result(
            True,
            "resume_rule",
            request_id,
            target=target,
        )

    def _command_run_guardian(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        config = self._config()
        check = next(
            (
                item
                for item in config.get("checks", [])
                if item.get("id") == target
            ),
            None,
        )
        if check is None:
            raise ValueError(f"Guardian nicht gefunden: {target}")
        result = load_guardian(check).run()
        return self._result(
            True,
            "run_guardian",
            request_id,
            target=target,
            result=result.to_dict(),
        )

    def _command_test_beacon(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        config = self._config()
        channel = next(
            (
                item
                for item in config.get("notifications", {}).get("channels", [])
                if item.get("id") == target
            ),
            None,
        )
        if channel is None:
            raise ValueError(f"Beacon nicht gefunden: {target}")
        from notifications import test_channel
        test_channel(channel)
        return self._result(
            True,
            "test_beacon",
            request_id,
            target=target,
        )

    def _command_get_status(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        try:
            data = json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"checks": {}}
        checks = data.get("checks", {})
        if target:
            if target not in checks:
                raise ValueError(f"Guardian-Status nicht gefunden: {target}")
            return self._result(
                True,
                "get_status",
                request_id,
                target=target,
                status=checks[target],
            )
        return self._result(
            True,
            "get_status",
            request_id,
            guardians=checks,
        )

    def _command_mute_beacon(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        config = self._config()
        channels = config.get("notifications", {}).get("channels", [])
        if not any(item.get("id") == target for item in channels):
            raise ValueError(f"Beacon nicht gefunden: {target}")
        self.state.reload()
        self.state.data["muted_beacons"][target] = {
            "until": self._until(payload),
            "reason": str(payload.get("reason", "")),
        }
        self.state.save()
        return self._result(
            True,
            "mute_beacon",
            request_id,
            target=target,
            until=self.state.data["muted_beacons"][target]["until"],
        )

    def _command_unmute_beacon(self, payload, request_id):
        target = str(payload.get("target", "")).strip()
        self.state.reload()
        self.state.data["muted_beacons"].pop(target, None)
        self.state.save()
        return self._result(
            True,
            "unmute_beacon",
            request_id,
            target=target,
        )

    def _command_get_runtime(self, payload, request_id):
        return self._result(
            True,
            "get_runtime",
            request_id,
            runtime=self.state.snapshot(),
        )


    def _command_acknowledge(self, payload, request_id):
        if self.database is None:
            raise ValueError("Incident-Datenbank ist nicht verfügbar.")
        incident_id = int(payload.get("incident_id") or 0)
        if not incident_id:
            target = str(payload.get("target", "")).strip()
            incident = self.database.get_open_incident(target)
            if not incident:
                raise ValueError("Kein offener Incident gefunden.")
            incident_id = incident["id"]
        incident = self.database.acknowledge_incident(
            incident_id,
            actor=str(payload.get("actor", "Control API")),
            note=str(payload.get("note", "")),
        )
        return self._result(
            True,
            "acknowledge",
            request_id,
            incident=incident,
        )

    def _command_unacknowledge(self, payload, request_id):
        if self.database is None:
            raise ValueError("Incident-Datenbank ist nicht verfügbar.")
        incident_id = int(payload.get("incident_id") or 0)
        if not incident_id:
            raise ValueError("incident_id fehlt.")
        incident = self.database.unacknowledge_incident(incident_id)
        return self._result(
            True,
            "unacknowledge",
            request_id,
            incident=incident,
        )

    def _command_get_incidents(self, payload, request_id):
        if self.database is None:
            raise ValueError("Incident-Datenbank ist nicht verfügbar.")
        result = self.database.query_incidents(
            status=str(payload.get("status", "")),
            guardian_id=str(payload.get("target", "")),
            page=1,
            per_page=min(200, int(payload.get("limit", 50))),
        )
        return self._result(
            True,
            "get_incidents",
            request_id,
            incidents=result["rows"],
        )
