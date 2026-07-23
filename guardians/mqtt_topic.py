import json
import re
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from guardians.base import BaseGuardian


STATE_DIR = Path("/var/lib/lanaxy/guardian-state/mqtt")


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "mqtt_topic",
        "name": "MQTT Topic Guardian",
        "version": "2.0.1",
        "description": "Prüft MQTT-Broker, Topics, Payloads, Retain und Nachrichtenalter",
        "icon": "mqtt",
        "category": "Dienste",
        "service_family": "mqtt",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "mode": {"type": "select", "label": "Prüfmodus", "default": "topic", "options": [
            {"value": "broker", "label": "Nur Broker-Verbindung"},
            {"value": "topic", "label": "Topic und Payload"},
        ]},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 30, "min": 2},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 5, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "host": {"type": "text", "label": "MQTT Host", "required": True},
        "port": {"type": "number", "label": "MQTT Port", "default": 1883, "required": True, "min": 1},
        "user": {"type": "text", "label": "MQTT Benutzer"},
        "password": {"type": "password", "label": "MQTT Passwort", "secret": True},
        "client_id": {"type": "text", "label": "Client-ID", "hint": "Leer lassen für eine automatisch erzeugte eindeutige Client-ID."},
        "tls": {"type": "checkbox", "label": "TLS verwenden", "default": False},
        "tls_insecure": {"type": "checkbox", "label": "TLS-Zertifikatsfehler ignorieren", "default": False, "visible_if": {"field": "tls", "equals": "1"}},
        "ca_file": {"type": "text", "label": "Eigene CA-Datei", "visible_if": {"field": "tls", "equals": "1"}, "hint": "Optionaler lokaler Pfad zu einem CA-Zertifikat."},
        "topic": {"type": "text", "label": "Topic", "visible_if": {"field": "mode", "equals": "topic"}},
        "qos": {"type": "select", "label": "QoS", "default": "0", "visible_if": {"field": "mode", "equals": "topic"}, "options": [
            {"value": "0", "label": "0 – höchstens einmal"}, {"value": "1", "label": "1 – mindestens einmal"}, {"value": "2", "label": "2 – genau einmal"},
        ]},
        "retain_policy": {"type": "select", "label": "Retain-Verhalten", "default": "allow", "visible_if": {"field": "mode", "equals": "topic"}, "options": [
            {"value": "allow", "label": "Retained und neue Nachrichten erlauben"},
            {"value": "require", "label": "Retained Nachricht erforderlich"},
            {"value": "forbid", "label": "Retained Nachricht verbieten"},
        ]},
        "comparison": {"type": "select", "label": "Payload-Prüfung", "default": "none", "visible_if": {"field": "mode", "equals": "topic"}, "options": [
            {"value": "none", "label": "Nur Nachricht vorhanden"},
            {"value": "equals", "label": "Exakter Wert"},
            {"value": "contains", "label": "Text enthält"},
            {"value": "regex", "label": "Regulärer Ausdruck"},
            {"value": "json", "label": "JSON-Pfad entspricht Wert"},
            {"value": "numeric", "label": "Numerischer Wertebereich"},
        ]},
        "expected": {"type": "textarea", "label": "Erwarteter Wert / Ausdruck", "visible_if": {"field": "comparison", "in": ["equals", "contains", "regex"]}, "hint": "Bei Exakt, Enthält oder Regex. Bestehende Konfigurationen mit ‚Erwarteter Wert‘ bleiben kompatibel."},
        "json_path": {"type": "text", "label": "JSON-Pfad", "visible_if": {"field": "comparison", "equals": "json"}, "hint": "Punktnotation, zum Beispiel status.online oder devices.0.state."},
        "json_expected": {"type": "textarea", "label": "Erwarteter JSON-Wert", "visible_if": {"field": "comparison", "equals": "json"}},
        "numeric_min": {"type": "number", "label": "Minimalwert", "visible_if": {"field": "comparison", "equals": "numeric"}},
        "numeric_max": {"type": "number", "label": "Maximalwert", "visible_if": {"field": "comparison", "equals": "numeric"}},
        "max_age_seconds": {"type": "number", "label": "Maximales Nachrichtenalter (Sekunden)", "default": 0, "min": 0, "visible_if": {"field": "mode", "equals": "topic"}, "hint": "0 deaktiviert die Altersprüfung. LANaxy speichert den letzten Empfangszeitpunkt lokal."},
        "timestamp_path": {"type": "text", "label": "JSON-Pfad zum Zeitstempel", "visible_if": {"field": "mode", "equals": "topic"}, "hint": "Optional. Unterstützt Unix-Sekunden sowie ISO-8601. Ohne Angabe wird LANaxys Empfangszeit verwendet."},
    }

    REQUIRED = ("host",)

    @classmethod
    def validate_config(cls, check):
        super().validate_config(check)
        if check.get("mode", "topic") == "topic" and not str(check.get("topic", "")).strip():
            raise ValueError("Für den Topic-Modus ist ein MQTT-Topic erforderlich.")

    @staticmethod
    def _json_path(data, path):
        value = data
        for part in str(path).split("."):
            if part == "": continue
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value

    def _state_path(self):
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", self.id)
        return STATE_DIR / f"{safe}.json"

    def _load_state(self):
        try: return json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError): return {}

    def _save_state(self, payload, retained, received_at):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            path=self._state_path(); tmp=path.with_suffix('.tmp')
            tmp.write_text(json.dumps({"payload": payload, "retained": retained, "received_at": received_at}, ensure_ascii=False), encoding='utf-8')
            tmp.replace(path)
        except OSError:
            pass

    @staticmethod
    def _timestamp(value):
        if isinstance(value, (int,float)): return float(value)
        text=str(value).strip()
        try: return float(text)
        except ValueError: pass
        return datetime.fromisoformat(text.replace('Z','+00:00')).astimezone(timezone.utc).timestamp()

    def _check_payload(self, payload, details):
        comparison=self.check.get('comparison') or ('equals' if str(self.check.get('expected','')).strip() else 'none')
        expected=str(self.check.get('expected',''))
        if comparison=='none': return None
        if comparison=='equals' and payload.strip()!=expected.strip(): return f"Payload ist {payload!r}, erwartet {expected!r}"
        if comparison=='contains' and expected not in payload: return f"Payload enthält {expected!r} nicht"
        if comparison=='regex':
            try: matched=re.search(expected,payload) is not None
            except re.error as e: return f"Ungültiger regulärer Ausdruck: {e}"
            if not matched: return "Payload entspricht dem regulären Ausdruck nicht"
        if comparison=='json':
            try:
                obj=json.loads(payload); value=self._json_path(obj,self.check.get('json_path',''))
            except (ValueError,KeyError,IndexError,TypeError) as e: return f"JSON-Pfad konnte nicht gelesen werden: {e}"
            details['json_value']=value
            wanted=str(self.check.get('json_expected',''))
            if str(value).lower()!=wanted.lower(): return f"JSON-Wert ist {value!r}, erwartet {wanted!r}"
        if comparison=='numeric':
            try: value=float(payload.strip())
            except ValueError: return "Payload ist kein numerischer Wert"
            details['numeric_value']=value
            lo=self.check.get('numeric_min'); hi=self.check.get('numeric_max')
            if lo not in (None,'') and value<float(lo): return f"Wert {value:g} liegt unter {float(lo):g}"
            if hi not in (None,'') and value>float(hi): return f"Wert {value:g} liegt über {float(hi):g}"
        return None

    def run(self):
        started=time.monotonic(); host=str(self.check['host']); port=int(self.check.get('port',1883)); mode=self.check.get('mode','topic')
        topic=str(self.check.get('topic','')); event=threading.Event(); received={}; error={}
        details={"guardian":self.GUARDIAN,"mqtt_host":host,"mqtt_port":port,"mode":mode,"topic":topic or None}

        def on_connect(client, userdata, flags, rc, properties=None):
            code=int(rc)
            if code!=0: error['message']=f"MQTT Return Code {code}"; event.set(); return
            details['connected']=True
            if mode=='broker': event.set()
            else: client.subscribe(topic, qos=int(self.check.get('qos',0)))
        def on_message(client,userdata,message):
            received.update(payload=message.payload.decode('utf-8',errors='replace'), retained=bool(message.retain), received_at=time.time()); event.set()

        client_id=str(self.check.get('client_id','')).strip() or f"lanaxy-{self.id}-{int(time.time())}"
        try: client=mqtt.Client(client_id=client_id)
        except TypeError: client=mqtt.Client(client_id)
        if self.check.get('user'): client.username_pw_set(self.check['user'],self.check.get('password'))
        if self.check.get('tls'):
            client.tls_set(ca_certs=self.check.get('ca_file') or None, cert_reqs=ssl.CERT_NONE if self.check.get('tls_insecure') else ssl.CERT_REQUIRED)
            client.tls_insecure_set(bool(self.check.get('tls_insecure')))
        client.on_connect=on_connect; client.on_message=on_message
        try:
            client.connect(host,port,keepalive=max(10,self.timeout*2)); client.loop_start(); event.wait(self.timeout)
        except Exception as e: error['message']=str(e)
        finally:
            try: client.loop_stop(); client.disconnect()
            except Exception: pass
        ms=int((time.monotonic()-started)*1000)
        if error.get('message'): details['error']=error['message']; return self.critical(f"{self.name}: MQTT-Verbindung fehlgeschlagen: {error['message']}",ms,details)
        if mode=='broker':
            if not details.get('connected'): return self.critical(f"{self.name}: Broker antwortet nicht innerhalb des Timeouts",ms,details)
            return self.ok(f"{self.name}: MQTT-Broker erreichbar",ms,details)
        if not received:
            state=self._load_state(); max_age=int(self.check.get('max_age_seconds',0) or 0)
            if max_age and state.get('received_at'):
                age=time.time()-float(state['received_at']); details.update(last_known=True,message_age_seconds=round(age,1),retained=state.get('retained'))
                if age<=max_age:
                    payload=str(state.get('payload','')); problem=self._check_payload(payload,details)
                    if problem: return self.critical(f"{self.name}: {problem}",ms,details)
                    return self.ok(f"{self.name}: letzte bekannte Nachricht ist {age:.0f} Sekunden alt",ms,details)
            return self.critical(f"{self.name}: Topic {topic} liefert innerhalb von {self.timeout} Sekunden keine Nachricht",ms,details)
        payload=received['payload']; retained=received['retained']; received_at=received['received_at']; details.update(payload=payload,retained=retained)
        policy=self.check.get('retain_policy','allow')
        if policy=='require' and not retained: return self.critical(f"{self.name}: Topic liefert keine retained Nachricht",ms,details)
        if policy=='forbid' and retained: return self.critical(f"{self.name}: retained Nachricht ist nicht erlaubt",ms,details)
        timestamp_path=str(self.check.get('timestamp_path','')).strip()
        message_time=received_at
        if timestamp_path:
            try: message_time=self._timestamp(self._json_path(json.loads(payload),timestamp_path))
            except Exception as e: return self.critical(f"{self.name}: Zeitstempel konnte nicht gelesen werden: {e}",ms,details)
        age=max(0,time.time()-message_time); details['message_age_seconds']=round(age,1)
        max_age=int(self.check.get('max_age_seconds',0) or 0)
        if max_age and age>max_age: return self.critical(f"{self.name}: Nachricht ist {age:.0f} Sekunden alt (maximal {max_age})",ms,details)
        problem=self._check_payload(payload,details)
        self._save_state(payload,retained,message_time)
        if problem: return self.critical(f"{self.name}: {problem}",ms,details)
        return self.ok(f"{self.name}: Topic {topic} liefert einen gültigen Wert",ms,details)
