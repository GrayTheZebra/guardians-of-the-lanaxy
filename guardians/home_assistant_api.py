import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "home_assistant_api",
        "name": "Home Assistant API Guardian",
        "version": "1.0.0",
        "description": "Prüft Home Assistant und optional den Zustand einer Entity über die REST-API",
        "icon": "home-automation",
        "category": "Smart Home",
        "service_family": "home_assistant",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "check_mode": {
            "type": "select", "label": "Prüfmodus", "default": "system",
            "options": [
                {"value": "system", "label": "Home Assistant API"},
                {"value": "entity", "label": "Entity-Zustand"},
            ],
        },
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 10, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "base_url": {"type": "url", "label": "Home-Assistant-URL", "required": True, "hint": "Zum Beispiel http://homeassistant.local:8123"},
        "access_token": {"type": "password", "label": "Long-Lived Access Token", "required": True, "secret": True},
        "verify_tls": {"type": "checkbox", "label": "TLS-Zertifikat validieren", "default": True},
        "entity_id": {"type": "text", "label": "Entity-ID", "visible_if": {"field": "check_mode", "equals": "entity"}, "hint": "Zum Beispiel sensor.backup_last_success"},
        "state_check": {
            "type": "select", "label": "Zustandsprüfung", "default": "available",
            "visible_if": {"field": "check_mode", "equals": "entity"},
            "options": [
                {"value": "available", "label": "Nicht unavailable/unknown"},
                {"value": "exact", "label": "Exakter Zustand"},
                {"value": "numeric", "label": "Numerischer Wertebereich"},
                {"value": "any", "label": "Nur Existenz prüfen"},
            ],
        },
        "expected_state": {"type": "text", "label": "Erwarteter Zustand", "visible_if": {"field": "state_check", "equals": "exact"}},
        "numeric_min": {"type": "number", "label": "Minimalwert", "visible_if": {"field": "state_check", "equals": "numeric"}},
        "numeric_max": {"type": "number", "label": "Maximalwert", "visible_if": {"field": "state_check", "equals": "numeric"}},
        "warning_state_age_minutes": {"type": "number", "label": "Warning ab unverändertem Zustand (Minuten)", "default": 0, "min": 0, "visible_if": {"field": "check_mode", "equals": "entity"}},
        "critical_state_age_minutes": {"type": "number", "label": "Critical ab unverändertem Zustand (Minuten)", "default": 0, "min": 0, "visible_if": {"field": "check_mode", "equals": "entity"}},
        "warning_response_ms": {"type": "number", "label": "Warning ab Antwortzeit (ms)", "default": 1000, "min": 0},
        "critical_response_ms": {"type": "number", "label": "Critical ab Antwortzeit (ms)", "default": 5000, "min": 0},
    }

    REQUIRED = ("base_url", "access_token")

    @staticmethod
    def _parse_time(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None

    def run(self):
        mode = str(self.check.get("check_mode", "system"))
        base_url = str(self.check["base_url"]).rstrip("/") + "/"
        entity_id = str(self.check.get("entity_id", "")).strip()
        if mode == "entity" and not entity_id:
            return self.critical(f"{self.name}: Keine Entity-ID angegeben", details={"error_code": "entity_missing"})

        endpoint = "api/" if mode == "system" else f"api/states/{entity_id}"
        url = urljoin(base_url, endpoint)
        headers = {"Authorization": f"Bearer {self.check['access_token']}", "Content-Type": "application/json"}
        verify_tls = bool(self.check.get("verify_tls", True))
        started = time.monotonic()
        details = {"guardian": self.GUARDIAN, "url": url, "check_mode": mode, "entity_id": entity_id or None}
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout, verify=verify_tls)
            response_ms = int((time.monotonic() - started) * 1000)
        except requests.exceptions.SSLError as error:
            details["error"] = str(error)
            return self.critical(f"{self.name}: TLS-Zertifikatsfehler", details=details)
        except requests.exceptions.Timeout:
            return self.critical(f"{self.name}: Home Assistant antwortet nicht innerhalb von {self.timeout} Sekunden", int(self.timeout * 1000), details)
        except requests.RequestException as error:
            details["error"] = str(error)
            return self.critical(f"{self.name}: Home Assistant ist nicht erreichbar", details=details)

        details.update(status_code=response.status_code, response_ms=response_ms)
        if response.status_code == 401:
            return self.critical(f"{self.name}: Zugriffstoken wurde abgelehnt", response_ms, details)
        if response.status_code == 404 and mode == "entity":
            return self.critical(f"{self.name}: Entity {entity_id} wurde nicht gefunden", response_ms, details)
        if response.status_code != 200:
            return self.critical(f"{self.name}: Home Assistant meldet HTTP {response.status_code}", response_ms, details)

        try:
            payload = response.json()
        except ValueError:
            return self.critical(f"{self.name}: Home Assistant lieferte kein gültiges JSON", response_ms, details)

        if mode == "entity":
            state = str(payload.get("state", ""))
            attributes = payload.get("attributes") or {}
            details.update(state=state, friendly_name=attributes.get("friendly_name"), unit=attributes.get("unit_of_measurement"), last_changed=payload.get("last_changed"), last_updated=payload.get("last_updated"))
            state_check = str(self.check.get("state_check", "available"))
            if state_check == "available" and state.lower() in {"unavailable", "unknown", "none", ""}:
                return self.critical(f"{self.name}: {entity_id} ist {state or 'ohne Zustand'}", response_ms, details)
            if state_check == "exact" and state != str(self.check.get("expected_state", "")):
                return self.critical(f"{self.name}: {entity_id} ist {state}, erwartet wird {self.check.get('expected_state', '')}", response_ms, details)
            if state_check == "numeric":
                try:
                    value = float(state.replace(",", "."))
                except ValueError:
                    return self.critical(f"{self.name}: Zustand {state} ist nicht numerisch", response_ms, details)
                details["numeric_value"] = value
                raw_min, raw_max = self.check.get("numeric_min"), self.check.get("numeric_max")
                if raw_min not in (None, "") and value < float(raw_min):
                    return self.critical(f"{self.name}: Wert {value:g} liegt unter {float(raw_min):g}", response_ms, details)
                if raw_max not in (None, "") and value > float(raw_max):
                    return self.critical(f"{self.name}: Wert {value:g} liegt über {float(raw_max):g}", response_ms, details)

            changed = self._parse_time(payload.get("last_changed"))
            if changed:
                age_minutes = max(0.0, (datetime.now(timezone.utc) - changed).total_seconds() / 60)
                details["state_age_minutes"] = round(age_minutes, 2)
                critical_age = float(self.check.get("critical_state_age_minutes", 0) or 0)
                warning_age = float(self.check.get("warning_state_age_minutes", 0) or 0)
                if critical_age and age_minutes >= critical_age:
                    return self.critical(f"{self.name}: Zustand von {entity_id} ist seit {age_minutes:.1f} Minuten unverändert", response_ms, details)
                if warning_age and age_minutes >= warning_age:
                    return self.warning(f"{self.name}: Zustand von {entity_id} ist seit {age_minutes:.1f} Minuten unverändert", response_ms, details)

        critical_ms = int(self.check.get("critical_response_ms", 5000) or 0)
        warning_ms = int(self.check.get("warning_response_ms", 1000) or 0)
        if critical_ms and response_ms >= critical_ms:
            return self.critical(f"{self.name}: Home Assistant antwortet sehr langsam ({response_ms} ms)", response_ms, details)
        if warning_ms and response_ms >= warning_ms:
            return self.warning(f"{self.name}: Home Assistant antwortet langsam ({response_ms} ms)", response_ms, details)

        if mode == "entity":
            return self.ok(f"{self.name}: {entity_id} ist {details['state']}", response_ms, details)
        return self.ok(f"{self.name}: Home Assistant API ist erreichbar", response_ms, details)
