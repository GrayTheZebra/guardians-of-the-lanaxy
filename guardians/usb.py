import glob
import os
import time
from pathlib import Path

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "usb", "name": "USB Guardian", "version": "1.2.0",
        "description": "Überwacht USB-Geräte stabil über VID, PID, Seriennummer und serial-by-id",
        "icon": "usb", "category": "Hardware", "service_family": "usb",
    }
    CONFIG_SCHEMA = {
        "name":{"type":"text","label":"Name","required":True}, "id":{"type":"slug","label":"Guardian-ID"},
        "device_id":{"type":"hidden","label":"Geräte-ID"},
        "execution_source": {"type": "select", "label": "Prüfquelle", "default": "local", "options": [{"value": "local", "label": "Dieses LANaxy-System"}, {"value": "miniguard", "label": "MiniGuard"}]},
        "miniguard_id": {"type": "select", "label": "MiniGuard", "options": [], "visible_if": {"field": "execution_source", "equals": "miniguard"}, "required": True, "hint": "Der MiniGuard muss online sein und diesen Check unterstützen."},
        "interval":{"type":"number","label":"Intervall (Sekunden)","default":30,"min":5},
        "timeout":{"type":"number","label":"Timeout (Sekunden)","default":5,"min":1},
        "retries":{"type":"number","label":"Fehlversuche bis Critical","default":3,"min":1},
        "vendor_id":{"type":"text","label":"Vendor-ID (VID)","hint":"Vierstellige Hex-ID, zum Beispiel 10c4. Leer lassen, wenn ausschließlich serial-by-id geprüft wird."},
        "product_id":{"type":"text","label":"Product-ID (PID)","hint":"Vierstellige Hex-ID, zum Beispiel ea60."},
        "serial":{"type":"text","label":"Seriennummer","hint":"Empfohlen, wenn mehrere identische Geräte vorhanden sind."},
        "serial_by_id":{"type":"text","label":"/dev/serial/by-id Name oder Pfad","hint":"Vollständiger Pfad oder eindeutiger Teil des Symlink-Namens."},
        "require_device_node":{"type":"checkbox","label":"Gerätenode unter /dev muss vorhanden sein","default":False},
        "passthrough_type":{"type":"select","label":"Proxmox-Passthrough prüfen","default":"none","options":[{"value":"none","label":"Nicht prüfen"},{"value":"qemu","label":"QEMU-VM"},{"value":"lxc","label":"LXC-Container"}]},
        "passthrough_vmid":{"type":"number","label":"VM-/LXC-ID","min":1,"visible_if":{"field":"passthrough_type","in":["qemu","lxc"]},"hint":"Prüft auf einem Proxmox-MiniGuard zusätzlich die Konfiguration unter /etc/pve."},
    }
    REQUIRED=()
    @classmethod
    def validate_config(cls,check):
        super().validate_config(check)
        if not any(str(check.get(k,'')).strip() for k in ('vendor_id','product_id','serial','serial_by_id')):
            raise ValueError('Mindestens VID/PID, Seriennummer oder serial-by-id muss angegeben werden.')
    @staticmethod
    def _read(path):
        try:return Path(path).read_text(encoding='utf-8',errors='replace').strip()
        except OSError:return ''
    def run(self):
        if str(self.check.get("execution_source", "local")) == "miniguard":
            return self.remote("usb")
        started=time.monotonic(); vid=str(self.check.get('vendor_id','')).lower().replace('0x','').strip(); pid=str(self.check.get('product_id','')).lower().replace('0x','').strip(); serial=str(self.check.get('serial','')).strip(); byid=str(self.check.get('serial_by_id','')).strip()
        details={"guardian":self.GUARDIAN,"vendor_id":vid or None,"product_id":pid or None,"serial_expected":serial or None,"serial_by_id_expected":byid or None}
        links=[]
        for item in glob.glob('/dev/serial/by-id/*'):
            try: links.append({"name":Path(item).name,"path":item,"target":os.path.realpath(item),"exists":Path(os.path.realpath(item)).exists()})
            except OSError: pass
        details['serial_by_id_links']=links
        byid_matches=[]
        if byid:
            byid_name=Path(byid).name
            byid_matches=[x for x in links if byid == x['path'] or byid == x['name'] or byid_name == x['name']]
            # Vollständige by-id-Pfade direkt prüfen, statt ausschließlich von
            # der per glob() ermittelten Liste abhängig zu sein.
            if not byid_matches and byid.startswith('/dev/serial/by-id/') and os.path.lexists(byid):
                byid_matches=[{"name":byid_name,"path":byid,"target":os.path.realpath(byid),"exists":Path(os.path.realpath(byid)).exists()}]
            details['serial_by_id_match']=byid_matches
            if not byid_matches: return self.critical(f"{self.name}: kein passendes Gerät unter /dev/serial/by-id gefunden",details=details)
        matches=[]
        for dev in glob.glob('/sys/bus/usb/devices/*'):
            d=Path(dev); dvid=self._read(d/'idVendor').lower(); dpid=self._read(d/'idProduct').lower()
            if not dvid or not dpid: continue
            dserial=self._read(d/'serial')
            if vid and dvid!=vid: continue
            if pid and dpid!=pid: continue
            if serial and dserial!=serial: continue
            matches.append({"sys_path":str(d),"vendor_id":dvid,"product_id":dpid,"serial":dserial,"manufacturer":self._read(d/'manufacturer'),"product":self._read(d/'product'),"busnum":self._read(d/'busnum'),"devnum":self._read(d/'devnum')})
        details['matches']=matches
        if (vid or pid or serial) and not matches: return self.critical(f"{self.name}: USB-Gerät wurde in /sys nicht gefunden",details=details)
        # Ein eindeutiger serial-by-id-Treffer identifiziert das Gerät bereits stabil.
        # Ohne VID/PID/Seriennummer darf die allgemeine /sys-Liste daher nicht als
        # mehrdeutige Treffermenge gewertet werden.
        if len(matches)>1 and not serial and not byid_matches:
            return self.warning(f"{self.name}: {len(matches)} passende USB-Geräte gefunden; Seriennummer zur eindeutigen Zuordnung empfohlen",details=details)
        if self.check.get('require_device_node'):
            valid=[x for x in byid_matches if x['exists']]
            if not valid: return self.critical(f"{self.name}: passender Gerätenode unter /dev ist nicht vorhanden",details=details)
        device=matches[0] if matches else {}
        label=' '.join(x for x in (device.get('manufacturer'),device.get('product')) if x).strip() or (byid_matches[0]['name'] if byid_matches else 'USB-Gerät')
        ms=int((time.monotonic()-started)*1000)
        return self.ok(f"{self.name}: {label} ist vorhanden",ms,details)
