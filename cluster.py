from __future__ import annotations
import hashlib,json,secrets,socket,tempfile,os
from datetime import datetime,timezone
from pathlib import Path

STATE_PATH=Path('/var/lib/lanaxy/cluster.json')
def _now(): return datetime.now(timezone.utc).isoformat()
def _read():
    if not STATE_PATH.exists(): return {"enabled":False,"cluster_id":"","node_id":socket.gethostname(),"node_name":socket.gethostname(),"role":"standalone","peers":[],"revision":0}
    try: return json.loads(STATE_PATH.read_text())
    except Exception: return {"enabled":False,"cluster_id":"","node_id":socket.gethostname(),"node_name":socket.gethostname(),"role":"standalone","peers":[],"revision":0}
def _write(data):
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(dir=STATE_PATH.parent,prefix='.cluster-',suffix='.tmp')
    with os.fdopen(fd,'w') as h: json.dump(data,h,ensure_ascii=False,indent=2); h.flush(); os.fsync(h.fileno())
    os.chmod(tmp,0o600); os.replace(tmp,STATE_PATH)
def status():
    data=_read(); data['architecture_version']=1; data['planned_for']='LANaxy 2.x'; return data
def configure(cluster_id,node_id,node_name,enabled=False):
    data=_read(); data.update(enabled=bool(enabled),cluster_id=cluster_id.strip(),node_id=node_id.strip() or socket.gethostname(),node_name=node_name.strip() or node_id.strip() or socket.gethostname(),role='standby' if enabled else 'standalone',updated_at=_now()); _write(data); return data
def create_join_token():
    data=_read(); token=secrets.token_urlsafe(32); data['join_token_hash']=hashlib.sha256(token.encode()).hexdigest(); data['join_token_created_at']=_now(); _write(data); return token
def public_snapshot():
    d=status(); d.pop('join_token_hash',None); return d
