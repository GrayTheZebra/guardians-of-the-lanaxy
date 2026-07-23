import re
import time
from urllib.parse import quote

import requests

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "proxmox_api",
        "name": "Proxmox API Guardian",
        "version": "1.2.0",
        "description": "Prüft Proxmox-Nodes, virtuelle Maschinen, LXC-Container und Storages",
        "icon": "server",
        "category": "Virtualisierung",
        "service_family": "proxmox",
    }

    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "mode": {
            "type": "select", "label": "Prüfmodus", "default": "node",
            "options": [
                {"value": "node", "label": "Proxmox-Node"},
                {"value": "guest", "label": "VM oder LXC"},
                {"value": "storage", "label": "Proxmox-Storage"},
            ],
        },
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 60, "min": 10},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 10, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 3, "min": 1},
        "api_url": {"type": "url", "label": "Proxmox API URL", "default": "https://proxmox.example:8006", "required": True},
        "token_id": {
            "type": "text",
            "label": "API-Token-ID",
            "required": True,
            "hint": (
                "Empfohlen: In Proxmox einen eigenen Benutzer und API-Token anlegen, "
                "dem Token auf / die Rolle PVEAuditor mit Weitergabe zuweisen. "
                "Bei aktivierter Rechte-Trennung müssen Benutzer und Token passende Rechte besitzen. "
                "Beispiel: lanaxy@pve!monitoring"
            ),
            "help_url": "https://pve.proxmox.com/pve-docs/pveum-plain.html#pveum_tokens",
            "help_url_label": "Offizielle Proxmox-Dokumentation zu API-Tokens und Berechtigungen",
        },
        "token_secret": {"type": "password", "label": "API-Token-Secret", "required": True, "secret": True},
        "verify_tls": {"type": "checkbox", "label": "TLS-Zertifikat validieren", "default": True},
        "node": {"type": "text", "label": "Node-Name", "required": False, "hint": "Optional. Leer lassen für automatische Erkennung; bei mehreren Nodes muss einer ausgewählt werden."},
        "guest_type": {
            "type": "select", "label": "Gasttyp", "default": "lxc",
            "visible_if": {"field": "mode", "equals": "guest"},
            "options": [
                {"value": "lxc", "label": "LXC-Container"},
                {"value": "qemu", "label": "Virtuelle Maschine (QEMU)"},
            ],
        },
        "vmid": {"type": "number", "label": "VM-/LXC-ID", "visible_if": {"field": "mode", "equals": "guest"}, "min": 1},
        "expected_status": {
            "type": "select", "label": "Erwarteter Gaststatus", "default": "running",
            "visible_if": {"field": "mode", "equals": "guest"},
            "options": [
                {"value": "running", "label": "Läuft"},
                {"value": "stopped", "label": "Gestoppt"},
                {"value": "any", "label": "Beliebig, Gast muss nur existieren"},
            ],
        },
        "minimum_uptime_minutes": {
            "type": "number", "label": "Mindestlaufzeit (Minuten)", "default": 0, "min": 0,
            "visible_if": {"field": "mode", "in": ["node", "guest"]},
        },
        "storage": {"type": "text", "label": "Storage-ID", "visible_if": {"field": "mode", "equals": "storage"}, "hint": "Zum Beispiel local-lvm"},
        "warning_used_percent": {
            "type": "number", "label": "Warning ab Belegung (%)", "default": 80, "min": 0, "max": 100,
            "visible_if": {"field": "mode", "equals": "storage"},
        },
        "critical_used_percent": {
            "type": "number", "label": "Critical ab Belegung (%)", "default": 95, "min": 0, "max": 100,
            "visible_if": {"field": "mode", "equals": "storage"},
        },
    }

    REQUIRED = ("api_url", "token_id", "token_secret")

    @classmethod
    def validate_config(cls, check):
        super().validate_config(check)
        mode = check.get("mode", "node")
        if mode == "guest" and not check.get("vmid"):
            raise ValueError("Für den Gast-Modus ist eine VM-/LXC-ID erforderlich.")
        if mode == "storage" and not str(check.get("storage", "")).strip():
            raise ValueError("Für den Storage-Modus ist eine Storage-ID erforderlich.")

    @classmethod
    def discover_nodes(cls, check):
        base = str(check["api_url"]).rstrip("/")
        headers = {"Authorization": f"PVEAPIToken={check['token_id']}={check['token_secret']}"}
        timeout = float(check.get("timeout", 10) or 10)
        response = requests.get(
            base + "/api2/json/nodes",
            headers=headers,
            timeout=timeout,
            verify=bool(check.get("verify_tls", True)),
        )
        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("message") or payload.get("errors") or response.text
            except ValueError:
                message = response.text
            raise RuntimeError(f"Proxmox API {response.status_code}: {message}")
        payload = response.json()
        nodes = []
        for item in payload.get("data") or []:
            name = str(item.get("node") or "").strip()
            if name:
                nodes.append({"name": name, "status": item.get("status"), "id": item.get("id")})
        return nodes

    @classmethod
    def discover_guests(cls, check, node=None):
        nodes = cls.discover_nodes(check)
        available_nodes = [item["name"] for item in nodes]
        selected_node = str(node or check.get("node") or "").strip()
        if not selected_node:
            if len(available_nodes) == 1:
                selected_node = available_nodes[0]
            elif len(available_nodes) > 1:
                raise RuntimeError(
                    "Mehrere Proxmox-Nodes gefunden: "
                    + ", ".join(available_nodes)
                    + ". Bitte zuerst einen Node auswählen."
                )
            else:
                raise RuntimeError("Die Proxmox API hat keine Nodes zurückgegeben.")
        if selected_node not in available_nodes:
            raise RuntimeError(
                f"Der Node „{selected_node}“ wurde nicht gefunden. Verfügbar: "
                + ", ".join(available_nodes)
            )

        base = str(check["api_url"]).rstrip("/")
        headers = {"Authorization": f"PVEAPIToken={check['token_id']}={check['token_secret']}"}
        timeout = float(check.get("timeout", 10) or 10)
        verify_tls = bool(check.get("verify_tls", True))
        guests = []
        for guest_type, label in (("qemu", "VM"), ("lxc", "LXC")):
            response = requests.get(
                f"{base}/api2/json/nodes/{quote(selected_node, safe='')}/{guest_type}",
                headers=headers,
                timeout=timeout,
                verify=verify_tls,
            )
            if response.status_code >= 400:
                try:
                    payload = response.json()
                    message = payload.get("message") or payload.get("errors") or response.text
                except ValueError:
                    message = response.text
                raise RuntimeError(f"Proxmox API {response.status_code}: {message}")
            payload = response.json()
            for item in payload.get("data") or []:
                try:
                    vmid = int(item.get("vmid"))
                except (TypeError, ValueError):
                    continue
                guests.append({
                    "vmid": vmid,
                    "type": guest_type,
                    "type_label": label,
                    "name": str(item.get("name") or f"{label} {vmid}"),
                    "status": item.get("status"),
                    "node": selected_node,
                })
        guests.sort(key=lambda item: (item["type_label"], item["name"].casefold(), item["vmid"]))
        return selected_node, guests

    @classmethod
    def discover_backups(cls, check, node=None):
        nodes = cls.discover_nodes(check)
        selected = [item["name"] for item in nodes if not node or item["name"] == node]
        output = []
        for node_name in selected:
            try:
                storages = cls._request(check, f"/nodes/{quote(node_name, safe='')}/storage")
            except Exception:
                storages = []
            for storage in storages:
                storage_id = str(storage.get("storage", ""))
                if not storage_id or not storage.get("active", 1):
                    continue
                content = str(storage.get("content", ""))
                if "backup" not in content:
                    continue
                try:
                    items = cls._request(check, f"/nodes/{quote(node_name, safe='')}/storage/{quote(storage_id, safe='')}/content?content=backup")
                except Exception:
                    items = []
                for item in items:
                    output.append({
                        "node": node_name, "storage": storage_id,
                        "volid": str(item.get("volid", "")),
                        "size": int(item.get("size", 0) or 0),
                        "ctime": int(item.get("ctime", 0) or 0),
                        "format": str(item.get("format", "")),
                    })
        return output


    @classmethod
    def discover_guest_configs(cls, check, node=None):
        """Read QEMU/LXC configs and expose USB/PCI passthrough assignments."""
        _selected, guests = cls.discover_guests(check, node)
        output = []
        for guest in guests:
            path = f"/nodes/{quote(guest['node'], safe='')}/{guest['type']}/{guest['vmid']}/config"
            try:
                config = cls._request(check, path) or {}
            except Exception as exc:
                output.append({**guest, "config_error": str(exc), "usb": [], "pci": [], "mounts": []})
                continue
            usb=[]; pci=[]; mounts=[]
            for key,value in config.items():
                key_s=str(key); value_s=str(value)
                if key_s.startswith('usb') or key_s.startswith('dev'):
                    usb.append({"key":key_s,"value":value_s})
                elif key_s.startswith('hostpci'):
                    pci.append({"key":key_s,"value":value_s})
                elif key_s.startswith('mp') or key_s in {'rootfs','scsi0','sata0','virtio0'}:
                    mounts.append({"key":key_s,"value":value_s})
            output.append({**guest,"usb":usb,"pci":pci,"mounts":mounts,"config":config})
        return output

    @classmethod
    def discover_backup_jobs(cls, check):
        jobs=[]
        for path in ('/cluster/backup','/cluster/backup-info'):
            try:
                rows=cls._request(check,path) or []
                if isinstance(rows,list):
                    jobs=rows
                    if jobs: break
            except Exception:
                continue
        result=[]
        for row in jobs:
            item=dict(row)
            item['job_id']=str(row.get('id') or row.get('job-id') or row.get('storage') or 'backup-job')
            item['enabled']=not bool(row.get('disable',0))
            result.append(item)
        return result

    @classmethod
    def summarize_guest_backups(cls, check, node=None):
        backups=cls.discover_backups(check,node)
        latest={}
        pattern=re.compile(r'(?:vzdump-)?(qemu|lxc|vm|ct)-(\d+)',re.I)
        for item in backups:
            match=pattern.search(item.get('volid',''))
            if not match: continue
            kind=match.group(1).lower(); vmid=int(match.group(2))
            guest_type='qemu' if kind in {'qemu','vm'} else 'lxc'
            key=(item.get('node'),guest_type,vmid)
            if key not in latest or int(item.get('ctime',0))>int(latest[key].get('ctime',0)):
                latest[key]={**item,'guest_type':guest_type,'vmid':vmid}
        return list(latest.values())

    @classmethod
    def discover_storages(cls, check, node=None):
        nodes = cls.discover_nodes(check)
        names = [item["name"] for item in nodes]
        selected = str(node or check.get("node") or "").strip()
        if not selected:
            if len(names) == 1:
                selected = names[0]
            elif len(names) > 1:
                raise RuntimeError("Mehrere Proxmox-Nodes gefunden: " + ", ".join(names) + ". Bitte zuerst einen Node auswählen.")
            else:
                raise RuntimeError("Die Proxmox API hat keine Nodes zurückgegeben.")
        base = str(check["api_url"]).rstrip("/")
        headers = {"Authorization": f"PVEAPIToken={check['token_id']}={check['token_secret']}"}
        response = requests.get(
            f"{base}/api2/json/nodes/{quote(selected, safe='')}/storage",
            headers=headers,
            timeout=float(check.get("timeout", 10) or 10),
            verify=bool(check.get("verify_tls", True)),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Proxmox API {response.status_code}: {response.text}")
        storages = []
        for item in response.json().get("data") or []:
            storage = str(item.get("storage") or "").strip()
            if storage:
                total = float(item.get("total", 0) or 0)
                used = float(item.get("used", 0) or 0)
                storages.append({
                    "storage": storage,
                    "type": item.get("type"),
                    "active": item.get("active"),
                    "enabled": item.get("enabled"),
                    "used_percent": round(used / total * 100, 1) if total else None,
                    "node": selected,
                })
        storages.sort(key=lambda item: item["storage"].casefold())
        return selected, storages

    def _resolve_node(self):
        configured = str(self.check.get("node") or "").strip()
        if configured:
            return configured, None
        nodes = self.discover_nodes(self.check)
        if not nodes:
            raise RuntimeError("Die Proxmox API hat keine Nodes zurückgegeben.")
        if len(nodes) > 1:
            names = ", ".join(node["name"] for node in nodes)
            raise RuntimeError(
                "Mehrere Proxmox-Nodes gefunden: " + names
                + ". Bitte im Guardian einen Node auswählen."
            )
        return nodes[0]["name"], nodes

    def _get(self, path):
        base = str(self.check["api_url"]).rstrip("/")
        headers = {"Authorization": f"PVEAPIToken={self.check['token_id']}={self.check['token_secret']}"}
        response = requests.get(base + "/api2/json" + path, headers=headers, timeout=self.timeout, verify=bool(self.check.get("verify_tls", True)))
        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("message") or payload.get("errors") or response.text
            except ValueError:
                message = response.text
            raise RuntimeError(f"Proxmox API {response.status_code}: {message}")
        payload = response.json()
        return payload.get("data")

    def run(self):
        started = time.monotonic()
        mode = self.check.get("mode", "node")
        details = {"guardian": self.GUARDIAN, "mode": mode, "api_url": self.check["api_url"]}
        try:
            resolved_node, discovered_nodes = self._resolve_node()
            node = quote(resolved_node, safe="")
            details["node"] = resolved_node
            if discovered_nodes is not None:
                details["node_auto_detected"] = True
                details["discovered_nodes"] = discovered_nodes
            if mode == "node":
                data = self._get(f"/nodes/{node}/status") or {}
            elif mode == "guest":
                guest_type = self.check.get("guest_type", "lxc")
                vmid = int(self.check["vmid"])
                data = self._get(f"/nodes/{node}/{guest_type}/{vmid}/status/current") or {}
                details.update({"guest_type": guest_type, "vmid": vmid})
            else:
                storage = quote(str(self.check["storage"]).strip(), safe="")
                data = self._get(f"/nodes/{node}/storage/{storage}/status") or {}
                details["storage"] = self.check["storage"]
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as error:
            ms = int((time.monotonic() - started) * 1000)
            details["error"] = str(error)
            message = str(error)
            if "Connection refused" in message or "Errno 111" in message:
                message += " · Verbindung zum Proxmox-Dienst wurde abgelehnt. API-URL und Port prüfen; die Authentifizierung wurde noch nicht erreicht."
            return self.critical(f"{self.name}: Proxmox-Prüfung fehlgeschlagen: {message}", ms, details)

        ms = int((time.monotonic() - started) * 1000)
        if mode == "node":
            status = str(data.get("status", "unknown"))
            uptime = float(data.get("uptime") or 0)
            details.update({
                "status": status, "uptime_seconds": round(uptime),
                "cpu_percent": round(float(data.get("cpu") or 0) * 100, 1),
                "loadavg": data.get("loadavg"), "memory": data.get("memory"),
                "pveversion": data.get("pveversion"), "kernel_version": data.get("kversion"),
            })
            if status not in ("online", "unknown"):
                return self.critical(f"{self.name}: Proxmox-Node {resolved_node} ist {status}", ms, details)
            minimum = float(self.check.get("minimum_uptime_minutes", 0) or 0) * 60
            if minimum and uptime < minimum:
                return self.warning(f"{self.name}: Proxmox-Node läuft erst seit {uptime / 60:.1f} Minuten", ms, details)
            return self.ok(f"{self.name}: Proxmox-Node {resolved_node} ist erreichbar", ms, details)

        if mode == "guest":
            status = str(data.get("status", "unknown"))
            uptime = float(data.get("uptime") or 0)
            guest_name = data.get("name") or f"{self.check.get('guest_type', 'lxc')} {self.check['vmid']}"
            details.update({
                "name": guest_name, "status": status, "uptime_seconds": round(uptime),
                "cpu_percent": round(float(data.get("cpu") or 0) * 100, 1),
                "memory_used": data.get("mem"), "memory_max": data.get("maxmem"),
                "disk_used": data.get("disk"), "disk_max": data.get("maxdisk"),
                "ha_state": data.get("ha"),
            })
            expected = self.check.get("expected_status", "running")
            if expected != "any" and status != expected:
                return self.critical(f"{self.name}: {guest_name} ist {status}, erwartet wird {expected}", ms, details)
            minimum = float(self.check.get("minimum_uptime_minutes", 0) or 0) * 60
            if minimum and status == "running" and uptime < minimum:
                return self.warning(f"{self.name}: {guest_name} läuft erst seit {uptime / 60:.1f} Minuten", ms, details)
            return self.ok(f"{self.name}: {guest_name} ist {status}", ms, details)

        active = bool(data.get("active", 1))
        enabled = bool(data.get("enabled", 1))
        total = float(data.get("total") or 0)
        used = float(data.get("used") or 0)
        available = float(data.get("avail") or max(0, total - used))
        used_percent = used / total * 100 if total else 0
        details.update({
            "active": active, "enabled": enabled, "content": data.get("content"),
            "storage_type": data.get("type"), "total_bytes": round(total),
            "used_bytes": round(used), "available_bytes": round(available),
            "used_percent": round(used_percent, 1),
        })
        storage_name = self.check["storage"]
        if not enabled or not active:
            return self.critical(f"{self.name}: Storage {storage_name} ist nicht aktiv", ms, details)
        critical = float(self.check.get("critical_used_percent", 0) or 0)
        warning = float(self.check.get("warning_used_percent", 0) or 0)
        if critical and used_percent >= critical:
            return self.critical(f"{self.name}: Storage {storage_name} ist zu {used_percent:.1f} % belegt", ms, details)
        if warning and used_percent >= warning:
            return self.warning(f"{self.name}: Storage {storage_name} ist zu {used_percent:.1f} % belegt", ms, details)
        return self.ok(f"{self.name}: Storage {storage_name} ist aktiv und zu {used_percent:.1f} % belegt", ms, details)
