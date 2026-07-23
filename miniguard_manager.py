"""MiniGuard registry and protocol-v1 foundation.

The manager stores only hashed registration codes and agent tokens. Plain
credentials are returned once to the caller that creates/registers an agent.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import fcntl
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from inventory_intelligence import compare_inventories, normalize_inventory
except ModuleNotFoundError:
    # Safety fallback for partially extracted updates. The canonical
    # implementation remains in inventory_intelligence.py, but LANaxy must
    # still be able to start and report the incomplete installation.
    import hashlib as _inventory_hashlib
    import json as _inventory_json

    _INVENTORY_KINDS = (
        "usb", "pci", "disks", "zfs_pools", "serial_by_id", "backup_files",
    )

    def _inventory_text(value):
        return str(value or "").strip()

    def _inventory_identity(kind, item):
        if kind == "usb":
            parts = [item.get("vendor_id"), item.get("product_id"), item.get("serial_number"), item.get("serial_path"), item.get("device_path")]
        elif kind == "pci":
            parts = [item.get("address"), item.get("vendor_device_id"), item.get("description")]
        elif kind == "disks":
            parts = [item.get("serial"), item.get("wwn"), item.get("path") or item.get("name")]
        elif kind == "zfs_pools":
            parts = [item.get("name") or item.get("pool")]
        elif kind == "serial_by_id":
            parts = [item.get("path") or item.get("name")]
        elif kind == "backup_files":
            parts = [item.get("path")]
        else:
            parts = sorted((str(key), _inventory_text(value)) for key, value in item.items())
        raw = "|".join(_inventory_text(value) for value in parts if _inventory_text(value))
        if not raw:
            raw = _inventory_json.dumps(item, sort_keys=True, ensure_ascii=False)
        return f"{kind}:{_inventory_hashlib.sha256(raw.encode()).hexdigest()[:20]}"

    def _inventory_display_name(kind, item, aliases=None):
        identity = _inventory_identity(kind, item)
        aliases = aliases or {}
        if aliases.get(identity):
            return aliases[identity]
        fields = {
            "usb": ("display_name", "model_name", "description"),
            "pci": ("description", "address"),
            "disks": ("model", "path", "name"),
            "zfs_pools": ("name", "pool"),
            "serial_by_id": ("name", "path"),
            "backup_files": ("path",),
        }.get(kind, ())
        for field in fields:
            value = _inventory_text(item.get(field))
            if value:
                return value
        return identity

    def normalize_inventory(inventory, aliases=None):
        source = inventory or {}
        result = {}
        for kind in _INVENTORY_KINDS:
            rows = []
            for raw in source.get(kind, []) or []:
                if not isinstance(raw, dict):
                    continue
                row = dict(raw)
                row["inventory_id"] = _inventory_identity(kind, row)
                row["inventory_kind"] = kind
                row["effective_name"] = _inventory_display_name(kind, row, aliases)
                rows.append(row)
            result[kind] = rows
        return result

    def compare_inventories(previous, current, aliases=None):
        before = normalize_inventory(previous, aliases)
        after = normalize_inventory(current, aliases)
        changes = []
        for kind in _INVENTORY_KINDS:
            old = {row["inventory_id"]: row for row in before[kind]}
            new = {row["inventory_id"]: row for row in after[kind]}
            for key in sorted(new.keys() - old.keys()):
                changes.append({"change": "added", "kind": kind, "inventory_id": key, "name": new[key]["effective_name"], "item": new[key]})
            for key in sorted(old.keys() - new.keys()):
                changes.append({"change": "removed", "kind": kind, "inventory_id": key, "name": old[key]["effective_name"], "item": old[key]})
            for key in sorted(old.keys() & new.keys()):
                left = {k: v for k, v in old[key].items() if k != "effective_name"}
                right = {k: v for k, v in new[key].items() if k != "effective_name"}
                if left != right:
                    changes.append({"change": "changed", "kind": kind, "inventory_id": key, "name": new[key]["effective_name"], "before": old[key], "item": new[key]})
        return changes

PROTOCOL_VERSION = 1
SAFE_ACTIONS = {
    'refresh_inventory',
    'run_diagnostics',
    'fetch_logs',
    'check_tool',
    'restart_agent',
    'update_agent',
    'rollback_agent',
    'rotate_token',
    'sync_permissions',
}
DANGEROUS_ACTIONS = {'restart_host'}
ALL_ACTIONS = SAFE_ACTIONS | DANGEROUS_ACTIONS
DEFAULT_ACTION_PERMISSIONS = {
    **{name: True for name in SAFE_ACTIONS},
    **{name: False for name in DANGEROUS_ACTIONS},
}
DEFAULT_PATH = Path('/var/lib/lanaxy/miniguards.json')
class _InterProcessLock:
    """Thread- and process-safe lock for the shared MiniGuard registry.

    A fresh file handle is opened for every lock acquisition. This avoids
    inherited/shared handle state between the LANaxy core and web workers.
    """
    def __init__(self, lock_path: Path):
        self._thread_lock = threading.RLock()
        self._lock_path = lock_path
        self._local = threading.local()

    def __enter__(self):
        self._thread_lock.acquire()
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._lock_path.open("a+")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._local.handle = handle
            return self
        except Exception:
            self._thread_lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        handle = getattr(self._local, "handle", None)
        try:
            if handle is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
                self._local.handle = None
        finally:
            self._thread_lock.release()


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, _InterProcessLock] = {}


def _lock_for(path: Path) -> _InterProcessLock:
    """Return one process-local lock object for the registry's lock file.

    The lock file lives beside the registry in /var/lib/lanaxy. That directory
    is created and owned by LANLord and remains writable inside both hardened
    systemd services. /run/lanaxy may not exist when ProtectSystem=strict is
    active, which previously caused every agent poll to fail before the route's
    JSON error handler could respond.
    """
    lock_path = path.with_name(f"{path.name}.lock")
    key = str(lock_path.resolve(strict=False))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _InterProcessLock(lock_path)
            _LOCKS[key] = lock
        return lock


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {'protocol_version': PROTOCOL_VERSION, 'agents': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'protocol_version': PROTOCOL_VERSION, 'agents': []}
    if not isinstance(data, dict) or not isinstance(data.get('agents'), list):
        return {'protocol_version': PROTOCOL_VERSION, 'agents': []}
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def list_agents(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    with _lock_for(path):
        result = []
        now = _now()
        for agent in _read(path)['agents']:
            item = {k: v for k, v in agent.items() if not k.endswith('_hash')}
            last_seen = item.get('last_seen')
            online = False
            if last_seen:
                try:
                    online = now - datetime.fromisoformat(last_seen) < timedelta(minutes=3)
                except ValueError:
                    pass
            item['online'] = online and item.get('enabled', True)
            last_poll = item.get('last_poll')
            worker_ready = False
            if last_poll:
                try:
                    worker_ready = now - datetime.fromisoformat(last_poll) < timedelta(seconds=20)
                except ValueError:
                    pass
            item['worker_ready'] = worker_ready and item['online']
            result.append(item)
        return result


def create_agent(name: str, description: str = '', ttl_minutes: int = 30,
                 path: Path = DEFAULT_PATH) -> tuple[dict[str, Any], str]:
    name = name.strip()
    if not name:
        raise ValueError('Name fehlt.')
    ttl_minutes = max(5, min(int(ttl_minutes), 1440))
    agent_id = secrets.token_hex(8)
    code = secrets.token_urlsafe(24)
    agent = {
        'id': agent_id,
        'name': name,
        'description': description.strip(),
        'enabled': True,
        'registered': False,
        'created_at': _iso(),
        'registration_expires_at': _iso(_now() + timedelta(minutes=ttl_minutes)),
        'registration_code_hash': _hash(code),
        'hostname': '',
        'os': '',
        'agent_version': '',
        'protocol_version': None,
        'capabilities': [],
        'action_permissions': dict(DEFAULT_ACTION_PERMISSIONS),
        'last_seen': None,
    }
    with _lock_for(path):
        data = _read(path)
        data['agents'].append(agent)
        _write(path, data)
    return {k: v for k, v in agent.items() if not k.endswith('_hash')}, code


def delete_agent(agent_id: str, path: Path = DEFAULT_PATH) -> bool:
    with _lock_for(path):
        data = _read(path)
        before = len(data['agents'])
        data['agents'] = [a for a in data['agents'] if a.get('id') != agent_id]
        if len(data['agents']) == before:
            return False
        _write(path, data)
        return True


def register_agent(agent_id: str, code: str, payload: dict[str, Any],
                   path: Path = DEFAULT_PATH) -> str:
    with _lock_for(path):
        data = _read(path)
        for agent in data['agents']:
            if agent.get('id') != agent_id:
                continue
            if agent.get('registered'):
                raise ValueError('MiniGuard ist bereits registriert.')
            try:
                expires = datetime.fromisoformat(agent['registration_expires_at'])
            except (KeyError, ValueError):
                raise ValueError('Registrierungscode ist ungültig.')
            if _now() > expires:
                raise ValueError('Registrierungscode ist abgelaufen.')
            if not secrets.compare_digest(agent.get('registration_code_hash', ''), _hash(code)):
                raise ValueError('Registrierungscode ist ungültig.')
            protocol = int(payload.get('protocol_version', 0))
            if protocol != PROTOCOL_VERSION:
                raise ValueError(f'Nicht unterstützte Protokollversion {protocol}.')
            token = secrets.token_urlsafe(48)
            agent.update({
                'registered': True,
                'registration_code_hash': '',
                'registered_at': _iso(),
                'token_hash': _hash(token),
                'hostname': str(payload.get('hostname', ''))[:255],
                'os': str(payload.get('os', ''))[:255],
                'agent_version': str(payload.get('agent_version', ''))[:64],
                'protocol_version': protocol,
                'capabilities': sorted(set(str(x)[:64] for x in payload.get('capabilities', []))),
                'tools': {str(k)[:64]: bool(v) for k,v in (payload.get('tools') or {}).items()} if isinstance(payload.get('tools'), dict) else {},
                'action_permissions': {
                    **DEFAULT_ACTION_PERMISSIONS,
                    **{
                        str(k): bool(v)
                        for k, v in (payload.get('action_permissions') or {}).items()
                        if str(k) in ALL_ACTIONS
                    },
                },
                'last_seen': _iso(),
            })
            _write(path, data)
            return token
    raise ValueError('MiniGuard wurde nicht gefunden.')


def heartbeat(agent_id: str, token: str, payload: dict[str, Any],
              path: Path = DEFAULT_PATH) -> dict[str, Any]:
    with _lock_for(path):
        data = _read(path)
        for agent in data['agents']:
            if agent.get('id') != agent_id:
                continue
            if not agent.get('enabled', True):
                raise PermissionError('MiniGuard ist deaktiviert.')
            if not secrets.compare_digest(agent.get('token_hash', ''), _hash(token)):
                raise PermissionError('Agent-Token ist ungültig.')
            agent['last_seen'] = _iso()
            for key, limit in [('hostname', 255), ('os', 255), ('agent_version', 64)]:
                if key in payload:
                    agent[key] = str(payload[key])[:limit]
            if 'capabilities' in payload:
                agent['capabilities'] = sorted(set(str(x)[:64] for x in payload['capabilities']))
            if 'tools' in payload and isinstance(payload['tools'], dict):
                agent['tools'] = {str(k)[:64]: bool(v) for k,v in payload['tools'].items()}
            if 'action_permissions' in payload and isinstance(payload['action_permissions'], dict):
                reported = {
                    str(k): bool(v)
                    for k, v in payload['action_permissions'].items()
                    if str(k) in ALL_ACTIONS
                }
                agent['reported_action_permissions'] = reported
            if 'health' in payload and isinstance(payload['health'], dict):
                agent['health'] = {
                    str(k)[:64]: v
                    for k, v in payload['health'].items()
                    if str(k) in {'service_uptime_seconds', 'queue_failures', 'last_error', 'buffered_results'}
                }
            _write(path, data)
            return {'ok': True, 'protocol_version': PROTOCOL_VERSION, 'server_time': _iso()}
    raise PermissionError('MiniGuard wurde nicht gefunden.')



def _authenticate_agent(data: dict[str, Any], agent_id: str, token: str) -> dict[str, Any]:
    for agent in data.get('agents', []):
        if agent.get('id') != agent_id:
            continue
        if not agent.get('enabled', True):
            raise PermissionError('MiniGuard ist deaktiviert.')
        if not secrets.compare_digest(agent.get('token_hash', ''), _hash(token)):
            raise PermissionError('Agent-Token ist ungültig.')
        return agent
    raise PermissionError('MiniGuard wurde nicht gefunden.')


def enqueue_check(agent_id: str, check_type: str, parameters: dict[str, Any],
                  timeout: int = 15, path: Path = DEFAULT_PATH) -> str:
    allowed = {'system_info','smart','systemd','storage','usb','docker','system_load','file_age','network_share','backup','zfs_raid','package_updates','hardware_sensors','pci_device','hardware_inventory'}
    if check_type not in allowed:
        raise ValueError(f'Nicht unterstützter MiniGuard-Check: {check_type}')
    timeout = max(2, min(int(timeout), 120))
    with _lock_for(path):
        data = _read(path)
        agent = next((a for a in data['agents'] if a.get('id') == agent_id), None)
        if not agent or not agent.get('registered') or not agent.get('enabled', True):
            raise ValueError('MiniGuard ist nicht registriert oder deaktiviert.')
        if check_type not in set(agent.get('capabilities', [])):
            raise ValueError(f'MiniGuard unterstützt den Check {check_type} nicht.')
        task_id = secrets.token_hex(12)
        tasks = data.setdefault('tasks', [])
        tasks.append({
            'id': task_id, 'agent_id': agent_id, 'check_type': check_type,
            'parameters': parameters, 'status': 'pending', 'created_at': _iso(),
            'expires_at': _iso(_now() + timedelta(seconds=timeout + 10)),
        })
        data['tasks'] = tasks[-200:]
        _write(path, data)
        return task_id


def poll_check(agent_id: str, token: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    with _lock_for(path):
        data = _read(path)
        agent = _authenticate_agent(data, agent_id, token)
        now = _now()
        agent['last_poll'] = _iso(now)
        for task in data.setdefault('tasks', []):
            if task.get('agent_id') != agent_id or task.get('status') != 'pending':
                continue
            try:
                if now > datetime.fromisoformat(task['expires_at']):
                    task['status'] = 'expired'
                    continue
            except (KeyError, ValueError):
                task['status'] = 'expired'; continue
            task['status'] = 'running'; task['started_at'] = _iso()
            _write(path, data)
            payload = {
                'id': task['id'],
                'task_kind': task.get('task_kind', 'check'),
                'parameters': task.get('parameters') or {},
            }
            if payload['task_kind'] == 'action':
                payload['action_type'] = task.get('action_type')
            else:
                payload['check_type'] = task.get('check_type')
            return payload
        _write(path, data)
        return {}


def complete_check(agent_id: str, token: str, task_id: str, result: dict[str, Any],
                   path: Path = DEFAULT_PATH) -> dict[str, Any]:
    with _lock_for(path):
        data = _read(path)
        _authenticate_agent(data, agent_id, token)
        for task in data.setdefault('tasks', []):
            if task.get('id') == task_id and task.get('agent_id') == agent_id:
                task['status'] = 'done'; task['completed_at'] = _iso()
                task['result'] = result
                agent = next((a for a in data.get('agents', []) if a.get('id') == agent_id), None)
                if agent is not None:
                    if task.get('task_kind') == 'action':
                        agent['last_action_at'] = task['completed_at']
                        agent['last_action_type'] = task.get('action_type')
                        agent['last_action_status'] = result.get('status')
                        agent['last_action_message'] = str(result.get('message',''))[:500]
                        if task.get('action_type') == 'rotate_token' and task.get('new_token_hash') and result.get('status') == 'ok':
                            agent['token_hash'] = task['new_token_hash']
                            agent['token_rotated_at'] = task['completed_at']
                        if task.get('action_type') == 'sync_permissions' and result.get('status') == 'ok':
                            agent['reported_action_permissions'] = dict(task.get('parameters', {}).get('permissions') or {})
                        if task.get('action_type') == 'refresh_inventory' and result.get('status') == 'ok':
                            previous = agent.get('hardware_inventory') or {}
                            current = result.get('details') or {}
                            aliases = agent.get('inventory_aliases') or {}
                            changes = compare_inventories(previous, current, aliases) if previous else []
                            agent['hardware_inventory'] = current
                            agent['hardware_inventory_normalized'] = normalize_inventory(current, aliases)
                            agent['inventory_updated_at'] = task['completed_at']
                            if changes:
                                batch_id = secrets.token_hex(8)
                                for change in changes:
                                    change['batch_id'] = batch_id
                                    change['detected_at'] = task['completed_at']
                                    change['acknowledged_at'] = None
                                agent.setdefault('inventory_changes', []).extend(changes)
                                agent['inventory_changes'] = agent['inventory_changes'][-500:]
                    else:
                        agent['last_check_at'] = task['completed_at']
                        agent['last_check_type'] = task.get('check_type')
                        agent['last_check_status'] = result.get('status')
                        agent['last_check_message'] = str(result.get('message',''))[:500]
                        agent['last_check_duration_ms'] = int(result.get('duration_ms',0) or 0)
                _write(path, data)
                return {'ok': True}
    raise ValueError('MiniGuard-Check wurde nicht gefunden.')


def get_check_result(task_id: str, path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    with _lock_for(path):
        for task in _read(path).get('tasks', []):
            if task.get('id') == task_id:
                if task.get('status') == 'done':
                    return task.get('result') or {}
                if task.get('status') == 'expired':
                    return {'status':'unknown','message':'MiniGuard-Check ist abgelaufen.','details':{},'error_code':'check_expired'}
                return None
    return {'status':'unknown','message':'MiniGuard-Check wurde nicht gefunden.','details':{},'error_code':'check_missing'}


def execute_remote_check(agent_id: str, check_type: str, parameters: dict[str, Any],
                         timeout: int = 15, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    import time
    # A green heartbeat only proves basic connectivity. Remote checks require
    # the 1.1 worker to poll the queue continuously. Detect an old/stalled
    # worker before creating a task and return an actionable message.
    with _lock_for(path):
        data = _read(path)
        agent = next((a for a in data.get('agents', []) if a.get('id') == agent_id), None)
        if not agent:
            return {'status':'unknown','message':'MiniGuard wurde nicht gefunden.','details':{'agent_id':agent_id},'error_code':'agent_missing'}
        last_poll = agent.get('last_poll')
        poll_recent = False
        if last_poll:
            try:
                poll_recent = _now() - datetime.fromisoformat(last_poll) < timedelta(seconds=20)
            except ValueError:
                pass
        if not poll_recent:
            return {
                'status':'unknown',
                'message':'MiniGuard ist erreichbar, aber der Remote-Check-Dienst ist nicht aktiv. Bitte den MiniGuard-Agenten aktualisieren oder neu starten.',
                'details':{'agent_id':agent_id,'agent_version':agent.get('agent_version'),'last_poll':last_poll},
                'error_code':'agent_worker_unavailable',
            }
    # Remote checks include queue pickup, local execution and result upload.
    # Five seconds is too tight even though it remains valid for local checks.
    remote_timeout = max(15, min(int(timeout), 120))
    task_id = enqueue_check(agent_id, check_type, parameters, remote_timeout, path)
    deadline = time.monotonic() + remote_timeout
    while time.monotonic() < deadline:
        result = get_check_result(task_id, path)
        if result is not None:
            return result
        time.sleep(0.1)
    return {'status':'unknown','message':'MiniGuard hat den Remote-Check nicht innerhalb des Zeitlimits abgeschlossen.','details':{'agent_id':agent_id,'timeout_seconds':remote_timeout},'error_code':'agent_timeout'}


def get_agent(agent_id: str, path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    return next((agent for agent in list_agents(path) if agent.get('id') == agent_id), None)


def set_action_permissions(agent_id: str, permissions: dict[str, bool],
                           path: Path = DEFAULT_PATH) -> dict[str, bool]:
    normalized = {
        name: bool(permissions.get(name, DEFAULT_ACTION_PERMISSIONS[name]))
        for name in ALL_ACTIONS
    }
    normalized['sync_permissions'] = True
    with _lock_for(path):
        data = _read(path)
        agent = next((item for item in data.get('agents', []) if item.get('id') == agent_id), None)
        if agent is None:
            raise ValueError('MiniGuard wurde nicht gefunden.')
        agent['action_permissions'] = normalized
        agent['permissions_updated_at'] = _iso()
        _write(path, data)
    return normalized


def set_agent_enabled(agent_id: str, enabled: bool, path: Path = DEFAULT_PATH) -> bool:
    with _lock_for(path):
        data = _read(path)
        agent = next((item for item in data.get('agents', []) if item.get('id') == agent_id), None)
        if agent is None:
            return False
        agent['enabled'] = bool(enabled)
        agent['enabled_updated_at'] = _iso()
        _write(path, data)
        return True


def enqueue_action(agent_id: str, action_type: str, parameters: dict[str, Any] | None = None,
                   timeout: int = 60, actor: str = 'LANaxy',
                   path: Path = DEFAULT_PATH) -> tuple[str, str | None]:
    if action_type not in ALL_ACTIONS:
        raise ValueError(f'Nicht unterstützte MiniGuard-Aktion: {action_type}')
    timeout = max(5, min(int(timeout), 300))
    secret_value = None
    with _lock_for(path):
        data = _read(path)
        agent = next((item for item in data.get('agents', []) if item.get('id') == agent_id), None)
        if not agent or not agent.get('registered') or not agent.get('enabled', True):
            raise ValueError('MiniGuard ist nicht registriert oder deaktiviert.')
        permissions = {**DEFAULT_ACTION_PERMISSIONS, **(agent.get('action_permissions') or {})}
        if not permissions.get(action_type, False):
            raise PermissionError(f'Die Aktion {action_type} ist für diesen MiniGuard nicht freigegeben.')
        task_id = secrets.token_hex(12)
        task_parameters = dict(parameters or {})
        task = {
            'id': task_id,
            'agent_id': agent_id,
            'task_kind': 'action',
            'action_type': action_type,
            'parameters': task_parameters,
            'status': 'pending',
            'created_at': _iso(),
            'expires_at': _iso(_now() + timedelta(seconds=timeout + 30)),
            'actor': str(actor)[:255],
        }
        if action_type == 'rotate_token':
            secret_value = secrets.token_urlsafe(48)
            task['parameters']['new_token'] = secret_value
            task['new_token_hash'] = _hash(secret_value)
        data.setdefault('tasks', []).append(task)
        data['tasks'] = data['tasks'][-500:]
        agent['last_action_enqueued_at'] = task['created_at']
        agent['last_action_enqueued_type'] = action_type
        _write(path, data)
        return task_id, secret_value


def get_task(task_id: str, path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    with _lock_for(path):
        task = next((item for item in _read(path).get('tasks', []) if item.get('id') == task_id), None)
        if task is None:
            return None
        safe = {key: value for key, value in task.items() if key not in {'new_token_hash'}}
        if safe.get('action_type') == 'rotate_token':
            safe['parameters'] = {'new_token': '__REDACTED__'}
        return safe


def wait_for_task(task_id: str, timeout: int = 90, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    import time
    deadline = time.monotonic() + max(1, int(timeout))
    while time.monotonic() < deadline:
        task = get_task(task_id, path)
        if task is None:
            return {'status': 'unknown', 'message': 'MiniGuard-Auftrag wurde nicht gefunden.', 'details': {}}
        if task.get('status') == 'done':
            return task.get('result') or {'status': 'unknown', 'message': 'MiniGuard lieferte kein Ergebnis.', 'details': {}}
        if task.get('status') == 'expired':
            return {'status': 'unknown', 'message': 'MiniGuard-Auftrag ist abgelaufen.', 'details': {}}
        time.sleep(0.2)
    return {'status': 'unknown', 'message': 'MiniGuard-Auftrag wurde nicht innerhalb des Zeitlimits abgeschlossen.', 'details': {}}


def recent_tasks(agent_id: str, limit: int = 20, path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    with _lock_for(path):
        rows = [
            item for item in _read(path).get('tasks', [])
            if item.get('agent_id') == agent_id
        ][-max(1, min(int(limit), 100)):]
    result = []
    for task in reversed(rows):
        safe = {key: value for key, value in task.items() if key not in {'new_token_hash'}}
        if safe.get('action_type') == 'rotate_token':
            safe['parameters'] = {'new_token': '__REDACTED__'}
        result.append(safe)
    return result


def set_inventory_alias(agent_id: str, inventory_id: str, alias: str, path: Path = DEFAULT_PATH) -> bool:
    alias=str(alias or '').strip()[:160]
    with _lock_for(path):
        data=_read(path); agent=next((a for a in data.get('agents',[]) if a.get('id')==agent_id),None)
        if agent is None: return False
        aliases=agent.setdefault('inventory_aliases',{})
        if alias: aliases[str(inventory_id)]=alias
        else: aliases.pop(str(inventory_id),None)
        agent['hardware_inventory_normalized']=normalize_inventory(agent.get('hardware_inventory') or {},aliases)
        _write(path,data); return True

def acknowledge_inventory_changes(agent_id: str, change_ids: list[str] | None=None, path: Path = DEFAULT_PATH) -> int:
    with _lock_for(path):
        data=_read(path); agent=next((a for a in data.get('agents',[]) if a.get('id')==agent_id),None)
        if agent is None:return 0
        wanted=set(change_ids or []); count=0; now=_iso()
        for change in agent.get('inventory_changes',[]):
            cid=f"{change.get('batch_id')}:{change.get('inventory_id')}:{change.get('change')}"
            if not change.get('acknowledged_at') and (not wanted or cid in wanted): change['acknowledged_at']=now; count+=1
        _write(path,data); return count
