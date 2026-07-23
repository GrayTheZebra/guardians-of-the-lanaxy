from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "hardware_sensors",
        "name": "Hardware-Sensoren Guardian",
        "version": "1.0.0",
        "description": "Prüft Temperaturen, Lüfter und IPMI-Sensoren",
        "icon": "uptime",
        "category": "Hardware",
        "service_family": "hardware",
    }
    CONFIG_SCHEMA = {
        "name": {"type":"text","label":"Name","required":True},
        "id": {"type":"slug","label":"Guardian-ID"},
        "device_id": {"type":"hidden","label":"Geräte-ID"},
        "execution_source": {"type":"select","label":"Prüfquelle","default":"miniguard","options":[{"value":"local","label":"Dieses LANaxy-System"},{"value":"miniguard","label":"MiniGuard"}]},
        "miniguard_id": {"type":"select","label":"MiniGuard","options":[],"visible_if":{"field":"execution_source","equals":"miniguard"},"required":True},
        "mode": {"type":"select","label":"Sensorquelle","default":"auto","options":[{"value":"auto","label":"Automatisch"},{"value":"lm_sensors","label":"lm-sensors"},{"value":"ipmi","label":"IPMI"}]},
        "warning_temperature": {"type":"number","label":"Warning ab Temperatur (°C)","default":75,"min":0},
        "critical_temperature": {"type":"number","label":"Critical ab Temperatur (°C)","default":90,"min":0},
        "minimum_fan_rpm": {"type":"number","label":"Warning unter Lüfterdrehzahl (RPM)","default":0,"min":0},
        "interval": {"type":"number","label":"Intervall (Sekunden)","default":120,"min":30},
        "timeout": {"type":"number","label":"Timeout (Sekunden)","default":15,"min":2},
        "retries": {"type":"number","label":"Fehlversuche bis Critical","default":2,"min":1},
    }
    REQUIRED = ()

    def run(self):
        if str(self.check.get("execution_source","miniguard")) == "miniguard":
            return self.remote("hardware_sensors")
        from miniguard_agent import check_hardware_sensors
        result = check_hardware_sensors(self.check)
        levels={"ok":0,"warning":1,"critical":2,"unknown":2}
        return self.result(result["status"],levels.get(result["status"],2),result["message"],result.get("duration_ms",0),result.get("details",{}))
