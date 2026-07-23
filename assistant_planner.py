from __future__ import annotations
from typing import Any


def _changes(existing:dict[str,Any], desired:dict[str,Any], fields:list[str]):
    rows=[]
    for key in fields:
        old=existing.get(key); new=desired.get(key)
        if old!=new: rows.append({"field":key,"old":old,"new":new})
    return rows


def pve_existing(checks):
    result={}
    for c in checks:
        g=c.get("guardian")
        key=None
        if g=="proxmox_api":
            mode=c.get("mode","node")
            if mode=="node": key=f"node|{c.get('node','')}"
            elif mode=="guest": key=f"guest|{c.get('node','')}|{c.get('guest_type','')}|{c.get('vmid','')}"
            elif mode=="storage": key=f"storage|{c.get('node','')}|{c.get('storage','')}"
        elif g=="usb":
            identity=c.get("serial_by_id") or c.get("serial") or f"{c.get('vendor_id','')}:{c.get('product_id','')}"
            key=f"usb|{identity}"
        elif g=="pci_device": key=f"pci|{c.get('pci_address','')}"
        elif g=="smart": key=f"disk|{c.get('device','')}"
        elif g=="zfs_raid" and c.get("pool"): key=f"zfs|{c.get('pool')}"
        elif g=="backup" and c.get("pattern"): key=f"backup|{c.get('pattern')}"
        if key: result[key]=c
    return result


def pbs_existing(checks):
    result={}
    for c in checks:
        guardian=c.get("guardian")
        key=None
        if guardian=="usb":
            identity=c.get("serial_by_id") or c.get("serial") or f"{c.get('vendor_id','')}:{c.get('product_id','')}"
            key=f"usb|{identity}"
        elif guardian=="pci_device": key=f"pci|{c.get('pci_address','')}"
        elif guardian=="smart": key=f"disk|{c.get('device','')}"
        elif guardian=="zfs_raid" and c.get("pool"): key=f"zfs|{c.get('pool')}"
        elif guardian!="proxmox_backup_server": continue
        mode=c.get("mode","server")
        if guardian=="proxmox_backup_server" and mode=="datastore": key=f"datastore|{c.get('datastore','')}"
        elif guardian=="proxmox_backup_server" and mode=="backup": key=f"backup|{c.get('datastore','')}|{c.get('namespace','')}|{c.get('backup_type','')}|{c.get('backup_id','')}"
        elif guardian=="proxmox_backup_server" and mode=="job": key=f"job|{c.get('job_type','')}|{c.get('job_id','')}"
        elif guardian=="proxmox_backup_server" and mode=="remote": key=f"remote|{c.get('remote','')}"
        if key: result[key]=c
    return result


def build_preview(selected, existing_map, desired_builder, update_existing=False):
    rows=[]
    for value in selected:
        desired=desired_builder(value)
        if not desired: continue
        key=desired.pop("_key")
        current=existing_map.get(key)
        if current:
            changes=_changes(current,desired,[k for k in desired if k not in {"id","guardian","token_secret"}])
            action="update" if update_existing and changes else "skip"
            rows.append({"key":key,"action":action,"name":desired.get("name"),"guardian":desired.get("guardian"),"existing_id":current.get("id"),"changes":changes})
        else:
            rows.append({"key":key,"action":"create","name":desired.get("name"),"guardian":desired.get("guardian"),"changes":[]})
    return rows
