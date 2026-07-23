import json
from datetime import datetime
from pathlib import Path
from guardians.base import BaseGuardian

class Guardian(BaseGuardian):
    GUARDIAN={"id":"smart","name":"SMART Guardian","version":"1.1.0","description":"Überwacht SMART- und NVMe-Gesundheitswerte lokaler Datenträger","icon":"hard-drive","category":"Hardware","service_family":"storage"}
    CONFIG_SCHEMA={
      "name":{"type":"text","label":"Name","required":True},"id":{"type":"slug","label":"Guardian-ID"},"device_id":{"type":"hidden","label":"Geräte-ID"},
      "execution_source":{"type":"select","label":"Prüfquelle","default":"miniguard","options":[{"value":"local","label":"Dieses LANaxy-System"},{"value":"miniguard","label":"MiniGuard"}]},
      "miniguard_id":{"type":"select","label":"MiniGuard","options":[],"visible_if":{"field":"execution_source","equals":"miniguard"},"required":True},
      "interval":{"type":"number","label":"Intervall (Sekunden)","default":300,"min":30},"timeout":{"type":"number","label":"Timeout (Sekunden)","default":20,"min":5},"retries":{"type":"number","label":"Fehlversuche bis Critical","default":2,"min":1},
      "device":{"type":"text","label":"Gerät","required":True,"placeholder":"/dev/sda oder /dev/nvme0","hint":"Nur direkte Gerätepfade unter /dev sind erlaubt."},
      "warning_temperature":{"type":"number","label":"Warning ab Temperatur (°C)","default":50,"min":0},"critical_temperature":{"type":"number","label":"Critical ab Temperatur (°C)","default":60,"min":0},
      "critical_reallocated":{"type":"number","label":"Critical ab reallocierten Sektoren","default":1,"min":0},"warning_percentage_used":{"type":"number","label":"Warning ab NVMe-Verbrauch (%)","default":80,"min":0,"max":100},
      "track_history":{"type":"checkbox","label":"SMART-Wertverlauf speichern","default":True},
      "history_limit":{"type":"number","label":"Maximale Verlaufspunkte","default":500,"min":10},
    }
    REQUIRED=('device',)
    @classmethod
    def validate_config(cls,c):
        super().validate_config(c); d=str(c.get('device',''))
        if not d.startswith('/dev/') or any(x in d for x in ('..',';','|','&','`','$')): raise ValueError('Ungültiger Gerätepfad. Erlaubt ist nur ein direkter Pfad unter /dev.')
    def _record_history(self, result):
        if not self.check.get("track_history", True):
            return
        details = dict(result.details or {})
        metrics = {
            key: details.get(key)
            for key in (
                "temperature_c", "reallocated_sectors", "pending_sectors",
                "uncorrectable_sectors", "media_errors", "percentage_used",
            )
            if details.get(key) is not None
        }
        if not metrics:
            return
        directory = Path("/var/lib/lanaxy/guardian-state/smart")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.id}.json"
        try:
            history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (OSError, json.JSONDecodeError):
            history = []
        previous = history[-1].get("metrics", {}) if history else {}
        changes = {
            key: metrics[key] - previous[key]
            for key in metrics
            if key in previous
            and isinstance(metrics[key], (int, float))
            and isinstance(previous[key], (int, float))
            and metrics[key] != previous[key]
        }
        history.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": result.status,
            "metrics": metrics,
            "changes": changes,
        })
        limit = max(10, int(self.check.get("history_limit", 500) or 500))
        history = history[-limit:]
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        result.details["smart_history_file"] = str(path)
        result.details["smart_metric_changes"] = changes
        result.details["smart_history_points"] = len(history)

    def run(self):
        if str(self.check.get('execution_source','miniguard'))=='miniguard':
            result = self.remote('smart')
        elif not shutil.which('smartctl'):
            result = self.result('unknown',2,f'{self.name}: smartctl ist nicht installiert',details={'error_code':'smartctl_missing'})
        else:
            # Local execution reuses the fixed MiniGuard implementation to keep results identical.
            from miniguard_agent import check_smart
            r=check_smart(self.check); levels={'ok':0,'warning':1,'critical':2,'unknown':2}
            result = self.result(r['status'],levels.get(r['status'],2),r['message'],r.get('duration_ms',0),r.get('details',{}))
        try:
            self._record_history(result)
        except OSError as error:
            result.details["smart_history_error"] = str(error)
        return result
