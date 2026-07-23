from __future__ import annotations
import hashlib, json
from typing import Any

KINDS = ('usb','pci','disks','zfs_pools','serial_by_id','backup_files')

def _text(value: Any) -> str:
    return str(value or '').strip()

def item_identity(kind: str, item: dict[str, Any]) -> str:
    if kind == 'usb':
        parts = [item.get('vendor_id'), item.get('product_id'), item.get('serial_number'), item.get('serial_path'), item.get('device_path')]
    elif kind == 'pci': parts = [item.get('address'), item.get('vendor_device_id'), item.get('description')]
    elif kind == 'disks': parts = [item.get('serial'), item.get('wwn'), item.get('path') or item.get('name')]
    elif kind == 'zfs_pools': parts = [item.get('name') or item.get('pool')]
    elif kind == 'serial_by_id': parts = [item.get('path') or item.get('name')]
    elif kind == 'backup_files': parts = [item.get('path')]
    else: parts = sorted((str(k), _text(v)) for k,v in item.items())
    raw='|'.join(_text(value) for value in parts if _text(value))
    if not raw: raw=json.dumps(item,sort_keys=True,ensure_ascii=False)
    return f'{kind}:{hashlib.sha256(raw.encode()).hexdigest()[:20]}'

def display_name(kind: str, item: dict[str, Any], aliases: dict[str,str] | None=None) -> str:
    identity=item_identity(kind,item)
    aliases=aliases or {}
    if aliases.get(identity): return aliases[identity]
    if kind=='usb': return _text(item.get('display_name') or item.get('model_name') or item.get('description') or identity)
    if kind=='pci': return _text(item.get('description') or item.get('address') or identity)
    if kind=='disks': return _text(item.get('model') or item.get('path') or item.get('name') or identity)
    if kind=='zfs_pools': return _text(item.get('name') or item.get('pool') or identity)
    if kind=='serial_by_id': return _text(item.get('name') or item.get('path') or identity)
    if kind=='backup_files': return _text(item.get('path') or identity)
    return identity

def normalize_inventory(inventory: dict[str,Any] | None, aliases: dict[str,str] | None=None) -> dict[str,list[dict[str,Any]]]:
    source=inventory or {}; result={}
    for kind in KINDS:
        rows=[]
        for raw in source.get(kind,[]) or []:
            if not isinstance(raw,dict): continue
            row=dict(raw); row['inventory_id']=item_identity(kind,row); row['inventory_kind']=kind; row['effective_name']=display_name(kind,row,aliases)
            rows.append(row)
        result[kind]=rows
    return result

def compare_inventories(previous: dict[str,Any] | None, current: dict[str,Any] | None, aliases: dict[str,str] | None=None) -> list[dict[str,Any]]:
    before=normalize_inventory(previous,aliases); after=normalize_inventory(current,aliases); changes=[]
    for kind in KINDS:
        old={row['inventory_id']:row for row in before[kind]}; new={row['inventory_id']:row for row in after[kind]}
        for key in sorted(new.keys()-old.keys()): changes.append({'change':'added','kind':kind,'inventory_id':key,'name':new[key]['effective_name'],'item':new[key]})
        for key in sorted(old.keys()-new.keys()): changes.append({'change':'removed','kind':kind,'inventory_id':key,'name':old[key]['effective_name'],'item':old[key]})
        for key in sorted(old.keys()&new.keys()):
            a={k:v for k,v in old[key].items() if k not in {'effective_name'}}; b={k:v for k,v in new[key].items() if k not in {'effective_name'}}
            if a != b: changes.append({'change':'changed','kind':kind,'inventory_id':key,'name':new[key]['effective_name'],'before':old[key],'item':new[key]})
    return changes
