import os
import time

from guardians.base import BaseGuardian


def _meminfo():
    values = {}
    with open('/proc/meminfo', encoding='utf-8') as handle:
        for line in handle:
            key, value = line.split(':', 1)
            values[key] = int(value.strip().split()[0]) * 1024
    return values


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "system_load", "name": "Systemlast Guardian", "version": "1.1.0",
        "description": "Prüft Load, RAM, Swap und Uptime eines Linux-Systems",
        "icon": "activity", "category": "System", "service_family": "system",
    }
    CONFIG_SCHEMA = {
        "name": {"type":"text","label":"Name","required":True}, "id":{"type":"slug","label":"Guardian-ID"},
        "device_id":{"type":"hidden","label":"Geräte-ID"}, "interval":{"type":"number","label":"Intervall (Sekunden)","default":60,"min":10},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True, "hint": "Der MiniGuard muss online sein und diesen Check unterstützen."},
        "timeout":{"type":"number","label":"Timeout (Sekunden)","default":5,"min":1}, "retries":{"type":"number","label":"Fehlversuche bis Critical","default":3,"min":1},
        "warning_load_percent":{"type":"number","label":"Warning Load (% der CPU-Kerne)","default":80,"min":0},
        "critical_load_percent":{"type":"number","label":"Critical Load (% der CPU-Kerne)","default":120,"min":0},
        "warning_ram_percent":{"type":"number","label":"Warning RAM-Auslastung (%)","default":80,"min":0},
        "critical_ram_percent":{"type":"number","label":"Critical RAM-Auslastung (%)","default":95,"min":0},
        "warning_swap_percent":{"type":"number","label":"Warning Swap-Auslastung (%)","default":50,"min":0},
        "critical_swap_percent":{"type":"number","label":"Critical Swap-Auslastung (%)","default":90,"min":0},
        "minimum_uptime_minutes":{"type":"number","label":"Mindest-Uptime (Minuten)","default":0,"min":0},
    }
    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("system_load")
        started = time.monotonic(); details={"guardian":self.GUARDIAN}
        try:
            load1, load5, load15 = os.getloadavg(); cores = os.cpu_count() or 1
            load_percent = load5 / cores * 100
            mem = _meminfo(); total=mem.get('MemTotal',0); available=mem.get('MemAvailable',mem.get('MemFree',0))
            ram_percent = ((total-available)/total*100) if total else 0
            swap_total=mem.get('SwapTotal',0); swap_free=mem.get('SwapFree',0)
            swap_percent=((swap_total-swap_free)/swap_total*100) if swap_total else 0
            with open('/proc/uptime', encoding='utf-8') as f: uptime=float(f.read().split()[0])
        except OSError as error:
            return self.critical(f"{self.name}: Systemdaten konnten nicht gelesen werden: {error}", details={"error":str(error)})
        details.update(cpu_cores=cores,load_1=round(load1,2),load_5=round(load5,2),load_15=round(load15,2),load_percent=round(load_percent,1),ram_percent=round(ram_percent,1),swap_percent=round(swap_percent,1),uptime_seconds=round(uptime))
        critical=[]; warning=[]
        minimum=float(self.check.get('minimum_uptime_minutes',0) or 0)*60
        if minimum and uptime < minimum: critical.append(f"Uptime nur {uptime/60:.1f} Minuten")
        for value, w, c, label in [
            (load_percent,'warning_load_percent','critical_load_percent','Load'),
            (ram_percent,'warning_ram_percent','critical_ram_percent','RAM'),
            (swap_percent,'warning_swap_percent','critical_swap_percent','Swap')]:
            cv=float(self.check.get(c,0) or 0); wv=float(self.check.get(w,0) or 0)
            if cv and value >= cv: critical.append(f"{label} {value:.1f} %")
            elif wv and value >= wv: warning.append(f"{label} {value:.1f} %")
        ms=int((time.monotonic()-started)*1000)
        if critical: return self.critical(f"{self.name}: "+', '.join(critical),ms,details)
        if warning: return self.warning(f"{self.name}: "+', '.join(warning),ms,details)
        return self.ok(f"{self.name}: Load {load_percent:.1f} %, RAM {ram_percent:.1f} %, Swap {swap_percent:.1f} %",ms,details)
