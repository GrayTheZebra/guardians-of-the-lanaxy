import copy, re, secrets
from custom_portals import discover_portals, resolve_portal_class
SECRET_PLACEHOLDER="••••••••"

def catalog():
 return {x["module"]:x for x in discover_portals() if x.get("status")=="loaded"}

def slugify(v):
 v=re.sub(r"[^a-z0-9]+","_",v.lower()).strip("_") or "portal"; return v

def next_id(items,name):
 base=slugify(name); n=1
 while any(x.get("id")==f"{base}_{n}" for x in items): n+=1
 return f"{base}_{n}"

def build_portal(form,portal_type,existing=None,all_items=None):
 item=copy.deepcopy(existing or {}); meta=catalog().get(portal_type)
 if not meta: raise ValueError("Unbekannter Portal-Typ.")
 item["type"]=portal_type
 for key,field in meta["schema"].items():
  raw=form.get(key)
  if field.get("secret") and raw==SECRET_PLACEHOLDER: continue
  if field.get("type")=="generated_secret":
   value=str(raw or "").strip() or item.get(key) or secrets.token_urlsafe(32)
  elif field.get("type")=="checkbox": value=raw=="1"
  elif field.get("type")=="command_checkboxes":
   if form.get(f"{key}__all")=="1": value="*"
   else:
    selected=[str(x).strip() for x in form.getlist(key) if str(x).strip()]
    value=",".join(selected)
  elif raw is None or str(raw).strip()=="": value=field.get("default")
  elif field.get("type")=="number": value=int(raw)
  else: value=str(raw).strip()
  if value is None and not field.get("required"): item.pop(key,None)
  else: item[key]=value
 item["enabled"]=form.get("enabled")=="1"
 if not item.get("name"): raise ValueError("Name fehlt.")
 if not item.get("id"): item["id"]=next_id(all_items or [],item["name"])
 resolve_portal_class(portal_type).validate_config(item)
 return item
