import time
from urllib.parse import quote

import requests

from guardians.base import BaseGuardian


class Guardian(BaseGuardian):
    GUARDIAN = {
        "id": "proxmox_backup_server",
        "name": "Proxmox Backup Server Guardian",
        "version": "1.3.0",
        "description": "Prüft PBS-Server, Datastores, Backup-Alter und Jobzustände",
        "icon": "archive",
        "category": "Virtualisierung",
        "service_family": "proxmox",
    }
    CONFIG_SCHEMA = {
        "name": {"type": "text", "label": "Name", "required": True},
        "id": {"type": "slug", "label": "Guardian-ID"},
        "device_id": {"type": "hidden", "label": "Geräte-ID"},
        "mode": {
            "type": "select", "label": "Prüfmodus", "default": "server",
            "options": [
                {"value": "server", "label": "PBS-Server"},
                {"value": "datastore", "label": "Datastore"},
                {"value": "backup", "label": "Backup-Gruppe"},
                {"value": "job", "label": "PBS-Job"},
                {"value": "remote", "label": "PBS-Remote"},
            ],
        },
        "api_url": {"type": "url", "label": "PBS API URL", "required": True, "default": "https://pbs.example:8007"},
        "token_id": {"type": "text", "label": "API-Token-ID", "required": True},
        "token_secret": {"type": "password", "label": "API-Token-Secret", "required": True, "secret": True},
        "verify_tls": {"type": "checkbox", "label": "TLS-Zertifikat validieren", "default": True},
        "datastore": {"type": "text", "label": "Datastore", "visible_if": {"field": "mode", "in": ["datastore", "backup"]}},
        "namespace": {"type": "text", "label": "Namespace", "visible_if": {"field": "mode", "equals": "backup"}},
        "backup_type": {"type": "text", "label": "Backup-Typ", "visible_if": {"field": "mode", "equals": "backup"}, "hint": "Zum Beispiel vm, ct oder host."},
        "backup_id": {"type": "text", "label": "Backup-ID", "visible_if": {"field": "mode", "equals": "backup"}},
        "warning_age_hours": {"type": "number", "label": "Warning ab Alter (Stunden)", "default": 26, "min": 1, "visible_if": {"field": "mode", "equals": "backup"}},
        "critical_age_hours": {"type": "number", "label": "Critical ab Alter (Stunden)", "default": 48, "min": 1, "visible_if": {"field": "mode", "equals": "backup"}},
        "job_type": {
            "type": "select", "label": "Jobtyp", "default": "verify",
            "options": [
                {"value": "verify", "label": "Verify"},
                {"value": "prune", "label": "Prune"},
                {"value": "sync", "label": "Sync"},
                {"value": "gc", "label": "Garbage Collection"},
            ],
            "visible_if": {"field": "mode", "equals": "job"},
        },
        "job_id": {"type": "text", "label": "Job-ID", "visible_if": {"field": "mode", "equals": "job"}},
        "remote": {"type": "text", "label": "Remote", "visible_if": {"field": "mode", "equals": "remote"}},
        "warning_used_percent": {"type": "number", "label": "Warning ab Belegung (%)", "default": 80, "min": 0, "max": 100, "visible_if": {"field": "mode", "equals": "datastore"}},
        "critical_used_percent": {"type": "number", "label": "Critical ab Belegung (%)", "default": 95, "min": 0, "max": 100, "visible_if": {"field": "mode", "equals": "datastore"}},
        "interval": {"type": "number", "label": "Intervall (Sekunden)", "default": 300, "min": 30},
        "timeout": {"type": "number", "label": "Timeout (Sekunden)", "default": 15, "min": 1},
        "retries": {"type": "number", "label": "Fehlversuche bis Critical", "default": 2, "min": 1},
    }
    REQUIRED = ("api_url", "token_id", "token_secret")

    @staticmethod
    def _request(check, path):
        base = str(check["api_url"]).rstrip("/")
        headers = {"Authorization": f"PBSAPIToken={check['token_id']}:{check['token_secret']}"}
        response = requests.get(
            base + "/api2/json" + path,
            headers=headers,
            timeout=int(float(check.get("timeout", 15))),
            verify=bool(check.get("verify_tls", True)),
        )
        response.raise_for_status()
        return response.json().get("data")

    def _get(self, path):
        return self._request(self.check, path)

    @classmethod
    def _try_paths(cls, check, paths, default=None):
        for path in paths:
            try:
                value=cls._request(check,path)
                if value is not None:
                    return value
            except Exception:
                continue
        return [] if default is None else default

    @classmethod
    def discover(cls, check):
        result={
            "version": cls._request(check,"/version"),
            "datastores": [], "namespaces": [], "groups": [], "snapshots": [],
            "jobs": [], "remotes": [], "tasks": [], "subscription": {}, "updates": [],
        }
        stores=cls._try_paths(check,["/admin/datastore","/config/datastore"],[]) or []
        for store in stores:
            name=store.get("store") or store.get("name")
            if not name: continue
            entry=dict(store); entry["name"]=name
            try:
                status=cls._request(check,f"/admin/datastore/{quote(str(name),safe='')}/status") or {}
                entry["status"]=status
                total=float(status.get("total",0) or 0); used=float(status.get("used",0) or 0)
                entry["used_percent"]=round(used/total*100,1) if total else 0
            except Exception as exc: entry["error"]=str(exc)
            result["datastores"].append(entry)
            namespaces=cls._try_paths(check,[
                f"/admin/datastore/{quote(str(name),safe='')}/namespace",
                f"/admin/datastore/{quote(str(name),safe='')}/namespaces",
            ],[]) or []
            for namespace in namespaces:
                item=dict(namespace) if isinstance(namespace,dict) else {"ns":str(namespace)}
                item["datastore"]=name; item["namespace"]=item.get("ns") or item.get("namespace") or ""
                result["namespaces"].append(item)
            groups=cls._try_paths(check,[f"/admin/datastore/{quote(str(name),safe='')}/groups"],[]) or []
            for group in groups:
                item=dict(group); item["datastore"]=name
                item["namespace"]=item.get("ns") or item.get("namespace") or ""
                result["groups"].append(item)
            snapshots=cls._try_paths(check,[f"/admin/datastore/{quote(str(name),safe='')}/snapshots"],[]) or []
            for snap in snapshots:
                item=dict(snap); item["datastore"]=name
                verify_state=item.get("verification") or item.get("verify-state") or item.get("verify_state")
                item["verify_state"]=verify_state
                result["snapshots"].append(item)
        job_paths={
            "verify":["/config/verify","/admin/verify"],
            "prune":["/config/prune","/admin/prune"],
            "sync":["/config/sync","/admin/sync"],
        }
        for kind,paths in job_paths.items():
            for job in cls._try_paths(check,paths,[]) or []:
                item=dict(job); item["job_type"]=kind
                item["job_id"]=job.get("id") or job.get("job-id") or job.get("store") or "unknown"
                result["jobs"].append(item)
        for store in result["datastores"]:
            result["jobs"].append({"job_type":"gc","job_id":store["name"],"store":store["name"]})
        result["remotes"]=cls._try_paths(check,["/config/remote","/admin/remote"],[]) or []
        result["tasks"]=cls._try_paths(check,["/nodes/localhost/tasks?limit=100","/nodes/localhost/tasks"],[]) or []
        result["subscription"]=cls._try_paths(check,["/nodes/localhost/subscription"],{}) or {}
        result["updates"]=cls._try_paths(check,["/nodes/localhost/apt/update","/nodes/localhost/apt/versions"],[]) or []
        # Attach latest task state to jobs where possible.
        for job in result["jobs"]:
            candidates=[]
            for task in result["tasks"]:
                worker=str(task.get("worker_id") or task.get("worker-id") or task.get("upid") or "")
                if str(job["job_id"]) in worker and job["job_type"] in worker.lower(): candidates.append(task)
            if candidates:
                candidates.sort(key=lambda row:int(row.get("starttime",0) or 0),reverse=True)
                job["last_task"]=candidates[0]
        return result

    def run(self):
        started = time.monotonic()
        try:
            mode = str(self.check.get("mode", "server"))
            version = self._get("/version")
            details = {"version": version, "mode": mode}
            if mode == "server":
                return self.ok(f"{self.name}: PBS ist erreichbar", int((time.monotonic()-started)*1000), details)
            datastore = str(self.check.get("datastore", "")).strip()
            if mode == "datastore":
                status = self._get(f"/admin/datastore/{quote(datastore, safe='')}/status")
                details["status"] = status
                total = float(status.get("total", 0) or 0)
                used = float(status.get("used", 0) or 0)
                percent = used / total * 100 if total else 0
                details["used_percent"] = round(percent, 1)
                if percent >= float(self.check.get("critical_used_percent", 95) or 95):
                    return self.critical(f"{self.name}: Datastore {percent:.1f} % belegt", details=details)
                if percent >= float(self.check.get("warning_used_percent", 80) or 80):
                    return self.warning(f"{self.name}: Datastore {percent:.1f} % belegt", details=details)
                return self.ok(f"{self.name}: Datastore {percent:.1f} % belegt", int((time.monotonic()-started)*1000), details)
            if mode == "backup":
                backup_type = str(self.check.get("backup_type", "")).strip()
                backup_id = str(self.check.get("backup_id", "")).strip()
                snapshots = self._get(
                    f"/admin/datastore/{quote(datastore, safe='')}/snapshots"
                    f"?backup-type={quote(backup_type, safe='')}&backup-id={quote(backup_id, safe='')}" + (f"&ns={quote(str(self.check.get('namespace','')), safe='')}" if self.check.get("namespace") else "")
                ) or []
                matching = [
                    row for row in snapshots
                    if str(row.get("backup-type", row.get("backup_type", ""))) == backup_type
                    and str(row.get("backup-id", row.get("backup_id", ""))) == backup_id
                ]
                if not matching:
                    return self.critical(f"{self.name}: Kein Backup für {backup_type}/{backup_id} gefunden", details=details)
                newest = max(matching, key=lambda row: int(row.get("backup-time", row.get("backup_time", 0)) or 0))
                backup_time = int(newest.get("backup-time", newest.get("backup_time", 0)) or 0)
                age_hours = max(0, (time.time() - backup_time) / 3600)
                warning_age = float(self.check.get("warning_age_hours", 26) or 26)
                critical_age = float(self.check.get("critical_age_hours", 48) or 48)
                details.update({
                    "latest_snapshot": newest,
                    "age_hours": round(age_hours, 1),
                    "warning_age_hours": warning_age,
                    "critical_age_hours": critical_age,
                })
                if age_hours >= critical_age:
                    exceeded = max(0.0, age_hours - critical_age)
                    details["active_max_age_hours"] = critical_age
                    details["exceeded_by_hours"] = round(exceeded, 1)
                    return self.critical(
                        f"{self.name}: Maximales Alter {critical_age:.1f} h, aktuell {age_hours:.1f} h, um {exceeded:.1f} h überschritten",
                        details=details,
                    )
                if age_hours >= warning_age:
                    exceeded = max(0.0, age_hours - warning_age)
                    details["active_max_age_hours"] = warning_age
                    details["exceeded_by_hours"] = round(exceeded, 1)
                    return self.warning(
                        f"{self.name}: Maximales Alter {warning_age:.1f} h, aktuell {age_hours:.1f} h, um {exceeded:.1f} h überschritten",
                        details=details,
                    )
                remaining = max(0.0, warning_age - age_hours)
                details["active_max_age_hours"] = warning_age
                details["remaining_hours"] = round(remaining, 1)
                return self.ok(
                    f"{self.name}: Maximales Alter {warning_age:.1f} h, aktuell {age_hours:.1f} h, noch {remaining:.1f} h verbleibend",
                    int((time.monotonic()-started)*1000),
                    details,
                )
            if mode == "remote":
                remote_name=str(self.check.get("remote","")).strip()
                remotes=self._try_paths(self.check,["/config/remote","/admin/remote"],[]) or []
                item=next((row for row in remotes if str(row.get("name") or row.get("remote"))==remote_name),None)
                details["remote"]=item
                if item is None:
                    return self.critical(f"{self.name}: PBS-Remote {remote_name} wurde nicht gefunden",details=details)
                return self.ok(f"{self.name}: PBS-Remote {remote_name} ist konfiguriert",int((time.monotonic()-started)*1000),details)
            job_type = str(self.check.get("job_type", "verify"))
            job_id = str(self.check.get("job_id", "")).strip()
            if job_type == "gc":
                status = self._get(f"/admin/datastore/{quote(job_id, safe='')}/gc")
            else:
                status = self._get(f"/admin/{quote(job_type, safe='')}/{quote(job_id, safe='')}")
            details["job"] = status
            state = str((status or {}).get("last-run-state") or (status or {}).get("last_run_state") or "unknown").lower()
            if state in {"error", "failed", "aborted"}:
                return self.critical(f"{self.name}: Letzter {job_type}-Lauf ist {state}", details=details)
            if state in {"unknown", ""}:
                return self.warning(f"{self.name}: Für den {job_type}-Job liegt kein eindeutiger Laufstatus vor", details=details)
            return self.ok(f"{self.name}: Letzter {job_type}-Lauf ist {state}", int((time.monotonic()-started)*1000), details)
        except Exception as error:
            return self.critical(f"{self.name}: PBS-Prüfung fehlgeschlagen: {error}", details={"error": str(error)})
