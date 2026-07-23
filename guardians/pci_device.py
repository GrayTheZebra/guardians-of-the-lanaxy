from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "pci_device",
        "name": "PCI / Passthrough Guardian",
        "version": "1.0.0",
        "description": "Prüft PCI-Geräte und optional Proxmox-Passthrough",
        "icon": "server",
        "category": "Hardware",
        "service_family": "hardware",
    }
    CONFIG_SCHEMA = {
        "name":{"type":"text","label":"Name","required":True},
        "id":{"type":"slug","label":"Guardian-ID"},
        "device_id":{"type":"hidden","label":"Geräte-ID"},
        "execution_source":{"type":"select","label":"Prüfquelle","default":"miniguard","options":[{"value":"local","label":"Dieses LANaxy-System"},{"value":"miniguard","label":"MiniGuard"}]},
        "miniguard_id":{"type":"select","label":"MiniGuard","options":[],"visible_if":{"field":"execution_source","equals":"miniguard"},"required":True},
        "pci_address":{"type":"text","label":"PCI-Adresse","hint":"Zum Beispiel 01:00.0"},
        "vendor_device":{"type":"text","label":"Vendor:Device-ID","hint":"Zum Beispiel 10de:2684"},
        "description_contains":{"type":"text","label":"Beschreibung enthält"},
        "passthrough_type":{"type":"select","label":"Proxmox-Passthrough","default":"none","options":[{"value":"none","label":"Nicht prüfen"},{"value":"qemu","label":"QEMU-VM"},{"value":"lxc","label":"LXC-Container"}]},
        "passthrough_vmid":{"type":"number","label":"VM-/LXC-ID","visible_if":{"field":"passthrough_type","in":["qemu","lxc"]},"min":1},
        "interval":{"type":"number","label":"Intervall (Sekunden)","default":300,"min":30},
        "timeout":{"type":"number","label":"Timeout (Sekunden)","default":10,"min":2},
        "retries":{"type":"number","label":"Fehlversuche bis Critical","default":2,"min":1},
    }
    REQUIRED = ()

    def run(self):
        if str(self.check.get("execution_source","miniguard")) == "miniguard":
            return self.remote("pci_device")
        from miniguard_agent import check_pci_device
        result=check_pci_device(self.check); levels={"ok":0,"warning":1,"critical":2,"unknown":2}
        return self.result(result["status"],levels.get(result["status"],2),result["message"],result.get("duration_ms",0),result.get("details",{}))
