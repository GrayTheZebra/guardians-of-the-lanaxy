import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path


LAUNCHPAD_DIR = Path("/var/lib/lanaxy/launchpad")
MAX_AGE_HOURS = 24


def ensure_directory():
    LAUNCHPAD_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(LAUNCHPAD_DIR, 0o700)


def new_mission():
    ensure_directory()
    mission_id = secrets.token_urlsafe(18)
    data = {
        "id": mission_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "steps": {},
    }
    save_mission(data)
    cleanup_missions()
    return data


def mission_path(mission_id):
    if not mission_id or any(
        character not in
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in mission_id
    ):
        raise ValueError("Ungültige Launchpad-Mission.")
    return LAUNCHPAD_DIR / f"{mission_id}.json"


def load_mission(mission_id):
    path = mission_path(mission_id)
    if not path.exists():
        raise FileNotFoundError("Launchpad-Mission wurde nicht gefunden.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Ungültige Launchpad-Mission.")
    return data


def save_mission(data):
    ensure_directory()
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = mission_path(data["id"])
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def delete_mission(mission_id):
    mission_path(mission_id).unlink(missing_ok=True)


def store_form(mission, step, form):
    values = {}
    for key in form.keys():
        items = form.getlist(key)
        values[key] = items if len(items) > 1 else items[0]
    values.pop("_csrf_token", None)
    mission.setdefault("steps", {})[step] = values
    save_mission(mission)


def form_values(mission, step):
    return mission.get("steps", {}).get(step, {})


def value_list(values, key):
    value = values.get(key, [])
    if isinstance(value, list):
        return value
    return [value] if value not in (None, "") else []


def cleanup_missions():
    ensure_directory()
    cutoff = datetime.now() - timedelta(hours=MAX_AGE_HOURS)
    for path in LAUNCHPAD_DIR.glob("*.json"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue
