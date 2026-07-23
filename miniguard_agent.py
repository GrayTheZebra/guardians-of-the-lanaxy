#!/usr/bin/env python3
"""LANaxy MiniGuard Agent – fixed local checks, no arbitrary commands."""
from __future__ import annotations
import argparse, glob, hashlib, json, os, platform, re, shutil, socket, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path
CONFIG=Path('/etc/miniguard/config.json'); VERSION='1.7.3'; PROTOCOL=1
AGENT_PATH=Path('/usr/local/bin/miniguard')
BACKUP_DIR=Path('/etc/miniguard/backups')
SAFE_ACTIONS={'refresh_inventory','run_diagnostics','fetch_logs','check_tool','restart_agent','update_agent','rollback_agent','rotate_token','sync_permissions'}
DANGEROUS_ACTIONS={'restart_host'}
DEFAULT_ACTION_PERMISSIONS={**{name:True for name in SAFE_ACTIONS},**{name:False for name in DANGEROUS_ACTIONS}}

def tool_status():
    return {name: bool(shutil.which(name)) for name in ('systemctl','docker','smartctl','lsusb','findmnt','zpool','sensors','ipmitool','lspci','checkupdates','apt-get','dnf')}

def capabilities():
    caps=['system_info','storage','usb','system_load','file_age','network_share','backup','package_updates','zfs_raid']
    if shutil.which('systemctl'): caps.append('systemd')
    if shutil.which('docker') or Path('/var/run/docker.sock').exists(): caps.append('docker')
    if shutil.which('smartctl'): caps.append('smart')
    if shutil.which('sensors') or shutil.which('ipmitool'): caps.append('hardware_sensors')
    if shutil.which('lspci'): caps.append('pci_device')
    caps.append('hardware_inventory')
    return caps

def request_json(url,payload,token=None,insecure=False,timeout=20):
    data=json.dumps(payload).encode(); headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=data,headers=headers,method='POST'); context=ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(req,timeout=timeout,context=context) as response:
            body=response.read().decode(); return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body=error.read().decode(errors='replace'); message=f'HTTP {error.code}: {error.reason}'
        try: message=str((json.loads(body) or {}).get('error') or message)
        except Exception:
            if body.strip(): message=body.strip()[:500]
        raise RuntimeError(message) from error
    except urllib.error.URLError as error: raise RuntimeError(f'LANaxy ist nicht erreichbar: {error.reason}') from error

def cfg():
    data=json.loads(CONFIG.read_text())
    data.setdefault('action_permissions',dict(DEFAULT_ACTION_PERMISSIONS))
    return data

def identity():
    config=cfg() if CONFIG.exists() else {'action_permissions':dict(DEFAULT_ACTION_PERMISSIONS)}
    return {
        'hostname':socket.gethostname(),
        'os':platform.platform(),
        'agent_version':VERSION,
        'protocol_version':PROTOCOL,
        'capabilities':capabilities(),
        'tools':tool_status(),
        'action_permissions':config.get('action_permissions') or {},
        'health':{
            'service_uptime_seconds':float(Path('/proc/uptime').read_text().split()[0]) if Path('/proc/uptime').exists() else None,
            'queue_failures':int(config.get('queue_failures',0) or 0),
            'last_error':str(config.get('last_error',''))[:500],
            'buffered_results':0,
        },
    }

def save_cfg(data):
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temp=CONFIG.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2))
    os.chmod(temp,0o600)
    os.replace(temp,CONFIG)

def register(a):
    lanaxy=a.lanaxy.rstrip('/')
    if CONFIG.exists():
        current=cfg(); cl=str(current.get('lanaxy','')).rstrip('/'); ca=str(current.get('agent_id',''))
        if cl==lanaxy and ca==a.agent_id and current.get('token'):
            print('MiniGuard ist bereits registriert. Installation wird aktualisiert.'); return
        raise RuntimeError(f'Auf diesem System ist bereits ein anderer MiniGuard registriert (LANaxy: {cl or "unbekannt"}, Agent-ID: {ca or "unbekannt"}). Bitte zuerst "miniguard uninstall" ausführen.')
    result=request_json(lanaxy+f'/api/miniguards/{a.agent_id}/register',{**identity(),'code':a.code},insecure=a.insecure)
    token=result.get('token');
    if not token: raise RuntimeError('LANaxy hat kein Agent-Token zurückgegeben.')
    save_cfg({'lanaxy':lanaxy,'agent_id':a.agent_id,'token':token,'insecure':a.insecure,'action_permissions':dict(DEFAULT_ACTION_PERMISSIONS),'queue_failures':0,'last_error':''})
    print('MiniGuard erfolgreich registriert.')

def heartbeat_once(c=None):
    c=c or cfg(); return request_json(c['lanaxy']+f"/api/miniguards/{c['agent_id']}/heartbeat",identity(),c['token'],bool(c.get('insecure')))

def result(status,message,details,start,error_code=None): return {'status':status,'message':message,'details':details,'duration_ms':int((time.monotonic()-start)*1000),'error_code':error_code}
def rfile(path):
    try:return Path(path).read_text(errors='replace').strip()
    except OSError:return ''

def check_systemd(p):
    start=time.monotonic(); name=p.get('name','Systemd'); unit=str(p.get('unit','')).strip(); unit += '' if '.' in unit else '.service'; details={'unit':unit}
    try: cp=subprocess.run(['systemctl','show',unit,'--no-pager','--property','LoadState','--property','ActiveState','--property','SubState','--property','UnitFileState','--property','NRestarts','--property','Description','--property','Result','--property','ExecMainStatus'],capture_output=True,text=True,timeout=int(p.get('timeout',5)),check=False)
    except Exception as e:return result('unknown',f'{name}: systemctl konnte nicht ausgeführt werden: {e}',details,start,'systemctl_error')
    vals={k:v for line in cp.stdout.splitlines() if '=' in line for k,v in [line.split('=',1)]}; details.update(vals)
    if vals.get('LoadState')=='not-found' or not vals:return result('critical',f'{name}: Unit {unit} wurde nicht gefunden',details,start)
    active=vals.get('ActiveState','unknown'); sub=vals.get('SubState','unknown'); exp=str(p.get('expected_active_state','active'))
    if active=='failed' or (exp!='any' and active!=exp):return result('critical',f'{name}: {unit} ist {active}/{sub}, erwartet wird {exp}',details,start)
    es=str(p.get('expected_sub_state','')).strip()
    if es and sub!=es:return result('critical',f'{name}: Substate ist {sub}, erwartet wird {es}',details,start)
    if p.get('require_enabled') and vals.get('UnitFileState') not in {'enabled','enabled-runtime','static','indirect','generated'}:return result('warning',f'{name}: {unit} ist nicht dauerhaft aktiviert',details,start)
    restarts=int(vals.get('NRestarts','0') or 0); cr=int(p.get('critical_restart_count',10) or 0); wr=int(p.get('warning_restart_count',3) or 0)
    if cr and restarts>=cr:return result('critical',f'{name}: Neustartzähler kritisch ({restarts})',details,start)
    if wr and restarts>=wr:return result('warning',f'{name}: erhöhter Neustartzähler ({restarts})',details,start)
    return result('ok',f'{name}: {unit} ist {active}/{sub}',details,start)

def check_storage(p):
    start=time.monotonic(); name=p.get('name','Speicherplatz'); path=Path(str(p.get('path','/'))); details={'path':str(path)}
    if not path.exists():return result('critical',f'{name}: Pfad {path} existiert nicht',details,start)
    if not path.is_dir():return result('critical',f'{name}: {path} ist kein Verzeichnis',details,start)
    if p.get('require_mountpoint') and not os.path.ismount(path):return result('critical',f'{name}: {path} ist kein eigener Mountpoint',details,start)
    try: st=os.statvfs(path)
    except OSError as e:return result('critical',f'{name}: Speicherstatistik konnte nicht gelesen werden',{'error':str(e),**details},start)
    total=st.f_blocks*st.f_frsize; free=st.f_bavail*st.f_frsize; fp=free/total*100 if total else 0; mb=free/1048576; ip=st.f_favail/st.f_files*100 if st.f_files else 100
    details.update(total_bytes=total,free_bytes=free,free_percent=round(fp,2),free_mb=round(mb,1),inode_free_percent=round(ip,2))
    if p.get('write_test'):
        try:
            with tempfile.NamedTemporaryFile(dir=path,prefix='.miniguard-write-',delete=True) as h: h.write(b'LANaxy'); h.flush(); os.fsync(h.fileno())
            details['write_test']='ok'
        except OSError as e:return result('critical',f'{name}: Schreibtest fehlgeschlagen',{'write_error':str(e),**details},start)
    critical=[]; warning=[]
    for val,w,c,label in [(fp,'warning_free_percent','critical_free_percent','% frei'),(mb,'warning_free_mb','critical_free_mb','MB frei'),(ip,'warning_free_inodes_percent','critical_free_inodes_percent','% Inodes frei')]:
        cv=float(p.get(c,0) or 0); wv=float(p.get(w,0) or 0)
        if cv and val<=cv:critical.append(f'nur {val:.1f} {label}')
        elif wv and val<=wv:warning.append(f'nur {val:.1f} {label}')
    if critical:return result('critical',f'{name}: '+', '.join(critical),details,start)
    if warning:return result('warning',f'{name}: '+', '.join(warning),details,start)
    return result('ok',f'{name}: {fp:.1f} % ({mb:.0f} MB) frei',details,start)

def check_usb(p):
    start=time.monotonic(); name=p.get('name','USB'); vid=str(p.get('vendor_id','')).lower().replace('0x','').strip(); pid=str(p.get('product_id','')).lower().replace('0x','').strip(); serial=str(p.get('serial','')).strip(); byid=str(p.get('serial_by_id','')).strip(); details={'vendor_id':vid,'product_id':pid,'serial_expected':serial}
    links=[]
    for item in glob.glob('/dev/serial/by-id/*'):
        links.append({'name':Path(item).name,'path':item,'target':os.path.realpath(item),'exists':Path(os.path.realpath(item)).exists()})
    bm=[]
    if byid:
        byid_name=Path(byid).name
        bm=[x for x in links if byid == x['path'] or byid == x['name'] or byid_name == x['name']]
        # Ein vollständig angegebener by-id-Pfad wird direkt geprüft. Das ist
        # robuster als ausschließlich auf die zuvor per glob() gelesene Liste
        # zu vertrauen und funktioniert auch bei abweichender Mount-/Namespace-Sicht.
        if not bm and byid.startswith('/dev/serial/by-id/') and os.path.lexists(byid):
            bm=[{'name':byid_name,'path':byid,'target':os.path.realpath(byid),'exists':Path(os.path.realpath(byid)).exists()}]
    details['serial_by_id_links']=links
    details['serial_by_id_match']=bm
    if byid and not bm:return result('critical',f'{name}: kein passendes Gerät unter /dev/serial/by-id gefunden',details,start)
    matches=[]
    for dev in glob.glob('/sys/bus/usb/devices/*'):
        d=Path(dev); dv=rfile(d/'idVendor').lower(); dp=rfile(d/'idProduct').lower(); ds=rfile(d/'serial')
        if not dv or not dp or (vid and dv!=vid) or (pid and dp!=pid) or (serial and ds!=serial):continue
        matches.append({'sys_path':str(d),'vendor_id':dv,'product_id':dp,'serial':ds,'manufacturer':rfile(d/'manufacturer'),'product':rfile(d/'product'),'busnum':rfile(d/'busnum'),'devnum':rfile(d/'devnum')})
    details['matches']=matches
    if (vid or pid or serial) and not matches:return result('critical',f'{name}: USB-Gerät wurde in /sys nicht gefunden',details,start)
    # Ein passender serial-by-id-Link ist bereits eine eindeutige, pfadstabile
    # Identifikation. Ohne VID/PID/Seriennummer darf die gesamte /sys-Liste
    # deshalb nicht als mehrdeutige Treffermenge behandelt werden.
    if len(matches)>1 and not serial and not bm:return result('warning',f'{name}: {len(matches)} passende USB-Geräte gefunden; Seriennummer empfohlen',details,start)
    if p.get('require_device_node') and not any(x['exists'] for x in bm):return result('critical',f'{name}: passender Gerätenode unter /dev ist nicht vorhanden',details,start)
    passthrough_type=str(p.get('passthrough_type','none') or 'none')
    passthrough_vmid=str(p.get('passthrough_vmid','') or '').strip()
    if passthrough_type in ('qemu','lxc') and passthrough_vmid:
        config_path=Path(f"/etc/pve/{'qemu-server' if passthrough_type=='qemu' else 'lxc'}/{passthrough_vmid}.conf")
        details['passthrough_config']=str(config_path)
        if not config_path.exists():return result('critical',f'{name}: Passthrough-Konfiguration {config_path.name} fehlt',details,start)
        config_text=config_path.read_text(encoding='utf-8',errors='replace').lower()
        needles=[x for x in (vid,pid,serial.lower(),Path(byid).name.lower() if byid else '') if x]
        details['passthrough_needles']=needles
        if not needles or not any(needle in config_text for needle in needles):
            return result('critical',f'{name}: USB-Gerät ist nicht an {passthrough_type.upper()} {passthrough_vmid} durchgereicht',details,start)
        details['passthrough_detected']=True
    d=matches[0] if matches else {}; label=' '.join(x for x in (d.get('manufacturer'),d.get('product')) if x).strip() or (bm[0]['name'] if bm else 'USB-Gerät')
    return result('ok',f'{name}: {label} ist vorhanden',details,start)

def meminfo():
    out={}
    with open('/proc/meminfo') as h:
        for line in h:key,val=line.split(':',1); out[key]=int(val.strip().split()[0])*1024
    return out

def check_system_load(p):
    start=time.monotonic(); name=p.get('name','Systemlast')
    try:
        l1,l5,l15=os.getloadavg(); cores=os.cpu_count() or 1; lp=l5/cores*100; m=meminfo(); total=m.get('MemTotal',0); avail=m.get('MemAvailable',m.get('MemFree',0)); rp=(total-avail)/total*100 if total else 0; st=m.get('SwapTotal',0); sf=m.get('SwapFree',0); sp=(st-sf)/st*100 if st else 0; uptime=float(Path('/proc/uptime').read_text().split()[0])
    except OSError as e:return result('unknown',f'{name}: Systemdaten konnten nicht gelesen werden: {e}',{'error':str(e)},start)
    details={'cpu_cores':cores,'load_1':round(l1,2),'load_5':round(l5,2),'load_15':round(l15,2),'load_percent':round(lp,1),'ram_percent':round(rp,1),'swap_percent':round(sp,1),'uptime_seconds':round(uptime)}; critical=[]; warning=[]
    if float(p.get('minimum_uptime_minutes',0) or 0)*60>uptime:critical.append(f'Uptime nur {uptime/60:.1f} Minuten')
    for val,w,c,label in [(lp,'warning_load_percent','critical_load_percent','Load'),(rp,'warning_ram_percent','critical_ram_percent','RAM'),(sp,'warning_swap_percent','critical_swap_percent','Swap')]:
        cv=float(p.get(c,0) or 0); wv=float(p.get(w,0) or 0)
        if cv and val>=cv:critical.append(f'{label} {val:.1f} %')
        elif wv and val>=wv:warning.append(f'{label} {val:.1f} %')
    if critical:return result('critical',f'{name}: '+', '.join(critical),details,start)
    if warning:return result('warning',f'{name}: '+', '.join(warning),details,start)
    return result('ok',f'{name}: Load {lp:.1f} %, RAM {rp:.1f} %, Swap {sp:.1f} %',details,start)

def check_file_age(p):
    start=time.monotonic(); name=p.get('name','Dateialter'); pattern=str(p.get('path') or p.get('file_pattern') or '').strip(); details={'pattern':pattern}
    matches=[Path(x) for x in glob.glob(pattern)] if any(c in pattern for c in '*?[') else [Path(pattern)]
    matches=[x for x in matches if x.is_file()]
    if not matches:return result('critical',f'{name}: Keine passende Datei gefunden',details,start)
    f=max(matches,key=lambda x:x.stat().st_mtime); st=f.stat(); age=(time.time()-st.st_mtime)/60; details.update(file=str(f),age_minutes=round(age,2),size_bytes=st.st_size,match_count=len(matches))
    minsize=int(p.get('minimum_size_bytes',0) or p.get('minimum_size_kb',0)*1024 or 0)
    if minsize and st.st_size<minsize:return result('critical',f'{name}: Datei ist zu klein ({st.st_size} Bytes)',details,start)
    c=float(p.get('critical_age_minutes',0) or 0); w=float(p.get('warning_age_minutes',0) or 0)
    if c and age>=c:return result('critical',f'{name}: Datei ist {age:.1f} Minuten alt',details,start)
    if w and age>=w:return result('warning',f'{name}: Datei ist {age:.1f} Minuten alt',details,start)
    return result('ok',f'{name}: {f.name} ist {age:.1f} Minuten alt',details,start)

def check_docker(p):
    start=time.monotonic(); name=p.get('name','Docker'); container=str(p.get('container','') or p.get('container_name','')).strip(); details={'container':container}
    if not shutil.which('docker'):return result('unknown',f'{name}: Docker-CLI ist nicht verfügbar',details,start,'docker_unavailable')
    if str(p.get('mode','container')) == 'engine':
        try: cp=subprocess.run(['docker','version','--format','{{json .Server}}'],capture_output=True,text=True,timeout=int(p.get('timeout',10)),check=False)
        except Exception as e:return result('unknown',f'{name}: Docker Engine konnte nicht geprüft werden: {e}',details,start,'docker_error')
        if cp.returncode:return result('critical',f'{name}: Docker Engine ist nicht erreichbar',{'stderr':cp.stderr.strip(),**details},start)
        try: details['server']=json.loads(cp.stdout)
        except Exception: details['server_raw']=cp.stdout.strip()
        return result('ok',f'{name}: Docker Engine ist erreichbar',details,start)
    try: cp=subprocess.run(['docker','inspect',container],capture_output=True,text=True,timeout=int(p.get('timeout',10)),check=False)
    except Exception as e:return result('unknown',f'{name}: Docker-Abfrage fehlgeschlagen: {e}',details,start,'docker_error')
    if cp.returncode:return result('critical',f'{name}: Container {container} wurde nicht gefunden',{'stderr':cp.stderr.strip(),**details},start)
    data=json.loads(cp.stdout)[0]; state=data.get('State',{}); status=state.get('Status','unknown'); details.update(status=status,running=state.get('Running'),restart_count=data.get('RestartCount',0),image=data.get('Config',{}).get('Image'),health=(state.get('Health') or {}).get('Status'))
    expected=str(p.get('expected_state','running'))
    if expected not in ('any',status):return result('critical',f'{name}: Container ist {status}, erwartet wird {expected}',details,start)
    if p.get('require_healthy') and details['health'] not in (None,'healthy'):return result('critical',f'{name}: Docker-Health ist {details["health"]}',details,start)
    rc=int(details['restart_count'] or 0); cr=int(p.get('critical_restart_count',10) or 0); wr=int(p.get('warning_restart_count',3) or 0)
    if cr and rc>=cr:return result('critical',f'{name}: Neustartzähler kritisch ({rc})',details,start)
    if wr and rc>=wr:return result('warning',f'{name}: erhöhter Neustartzähler ({rc})',details,start)
    return result('ok',f'{name}: Container {container} ist {status}',details,start)


def check_system_info(p):
    start=time.monotonic(); details=identity(); details.update({'python_version':platform.python_version(),'architecture':platform.machine(),'uptime_seconds':float(Path('/proc/uptime').read_text().split()[0]) if Path('/proc/uptime').exists() else None})
    return result('ok',f"MiniGuard auf {details['hostname']} ist betriebsbereit",details,start)

def check_smart(p):
    start=time.monotonic(); name=p.get('name','SMART'); device=str(p.get('device','')).strip(); details={'device':device}
    if not device.startswith('/dev/') or any(x in device for x in ('..',';','|','&','`','$')):
        return result('unknown',f'{name}: ungültiger Gerätepfad',details,start,'invalid_device')
    if not shutil.which('smartctl'):
        return result('unknown',f'{name}: smartctl ist nicht installiert',details,start,'smartctl_missing')
    cmd=['smartctl','--json','--all',device]
    try: cp=subprocess.run(cmd,capture_output=True,text=True,timeout=int(p.get('timeout',15)),check=False)
    except Exception as e:return result('unknown',f'{name}: SMART-Abfrage fehlgeschlagen: {e}',details,start,'smartctl_error')
    try:data=json.loads(cp.stdout or '{}')
    except Exception:return result('unknown',f'{name}: smartctl lieferte kein gültiges JSON',{'stderr':cp.stderr[-1000:],**details},start,'smartctl_json')
    details['smartctl_exit_status']=data.get('smartctl',{}).get('exit_status',cp.returncode)
    details['model_name']=data.get('model_name') or data.get('model_family')
    details['serial_number']=data.get('serial_number')
    passed=(data.get('smart_status') or {}).get('passed')
    temp=(data.get('temperature') or {}).get('current')
    nvme=data.get('nvme_smart_health_information_log') or {}
    if temp is None: temp=nvme.get('temperature')
    attrs=(data.get('ata_smart_attributes') or {}).get('table') or []
    amap={str(a.get('name','')).lower(): a.get('raw',{}).get('value',0) for a in attrs}
    def attr(*names):
        for n in names:
            for k,v in amap.items():
                if n in k:
                    try:return int(v)
                    except Exception:return 0
        return 0
    reallocated=attr('reallocated_sector','reallocated_event')
    pending=attr('current_pending_sector','pending_sector')
    uncorrectable=attr('offline_uncorrectable','uncorrectable_sector')
    media_errors=int(nvme.get('media_errors',0) or 0)
    critical_warning=int(nvme.get('critical_warning',0) or 0)
    percentage_used=nvme.get('percentage_used')
    details.update(passed=passed,temperature_c=temp,reallocated_sectors=reallocated,pending_sectors=pending,uncorrectable_sectors=uncorrectable,media_errors=media_errors,nvme_critical_warning=critical_warning,percentage_used=percentage_used)
    if passed is False or critical_warning or media_errors or pending or uncorrectable:
        return result('critical',f'{name}: SMART meldet einen kritischen Zustand',details,start)
    ct=float(p.get('critical_temperature',60) or 0); wt=float(p.get('warning_temperature',50) or 0)
    if temp is not None and ct and float(temp)>=ct:return result('critical',f'{name}: Temperatur kritisch ({temp} °C)',details,start)
    if reallocated and int(p.get('critical_reallocated',1) or 0) and reallocated>=int(p.get('critical_reallocated',1)):return result('critical',f'{name}: {reallocated} reallozierte Sektoren',details,start)
    if temp is not None and wt and float(temp)>=wt:return result('warning',f'{name}: Temperatur erhöht ({temp} °C)',details,start)
    if percentage_used is not None and int(percentage_used)>=int(p.get('warning_percentage_used',80) or 80):return result('warning',f'{name}: NVMe-Lebensdauer zu {percentage_used} % verbraucht',details,start)
    label=details.get('model_name') or device
    return result('ok',f'{name}: {label} meldet keine SMART-Probleme',details,start)


def check_network_share(p):
    start=time.monotonic(); name=p.get('name','SMB/NFS'); path=Path(str(p.get('path','')).strip()); details={'path':str(path)}
    if not path.exists(): return result('critical',f'{name}: Mountpoint {path} existiert nicht',details,start)
    if not shutil.which('findmnt'): return result('unknown',f'{name}: findmnt ist nicht verfügbar',details,start,'findmnt_missing')
    try: cp=subprocess.run(['findmnt','-J','-T',str(path)],capture_output=True,text=True,timeout=int(p.get('timeout',15)),check=False)
    except Exception as e: return result('unknown',f'{name}: Mountinformation konnte nicht gelesen werden: {e}',details,start,'findmnt_error')
    if cp.returncode: return result('critical',f'{name}: {path} ist nicht eingehängt',{'stderr':cp.stderr.strip(),**details},start)
    try: rows=(json.loads(cp.stdout or '{}').get('filesystems') or []); mount=rows[0] if rows else None
    except Exception as e: return result('unknown',f'{name}: findmnt lieferte ungültige Daten',{'error':str(e),**details},start,'findmnt_json')
    if not mount or os.path.abspath(str(mount.get('target',''))) != os.path.abspath(str(path)):
        return result('critical',f'{name}: {path} ist nicht als eigener Mountpoint eingehängt',{'detected_mount':mount,**details},start)
    fs_type=str(mount.get('fstype','')); details.update(source=mount.get('source'),target=mount.get('target'),fs_type=fs_type,options=mount.get('options'))
    expected={v.strip().lower() for v in str(p.get('expected_fs_types','')).split(',') if v.strip()}
    if expected and fs_type.lower() not in expected: return result('critical',f'{name}: Dateisystemtyp ist {fs_type}, erwartet wird {", ".join(sorted(expected))}',details,start)
    try:
        if p.get('read_test',True): next(os.scandir(path),None); details['read_test']='ok'
        if p.get('write_test'):
            with tempfile.NamedTemporaryFile(dir=path,prefix='.miniguard-share-test-',delete=True) as h: h.write(b'LANaxy'); h.flush(); os.fsync(h.fileno())
            details['write_test']='ok'
    except OSError as e: return result('critical',f'{name}: Zugriffstest auf {path} fehlgeschlagen: {e}',{'io_error':str(e),**details},start)
    ms=int((time.monotonic()-start)*1000); details['response_ms']=ms; cr=int(p.get('critical_response_ms',5000) or 0); wr=int(p.get('warning_response_ms',1000) or 0)
    if cr and ms>=cr:return result('critical',f'{name}: Netzwerkfreigabe reagiert sehr langsam ({ms} ms)',details,start)
    if wr and ms>=wr:return result('warning',f'{name}: Netzwerkfreigabe reagiert langsam ({ms} ms)',details,start)
    return result('ok',f'{name}: {fs_type}-Freigabe ist erreichbar',details,start)

def check_backup(p):
    start=time.monotonic(); name=p.get('name','Backup'); pattern=str(p.get('pattern','')).strip(); details={'pattern':pattern}
    ignored=('.tmp','.part','.partial','.incomplete'); matches=[]
    for raw in glob.glob(os.path.expanduser(pattern)):
        path=Path(raw)
        if not path.is_file(): continue
        if p.get('ignore_partial',True) and (path.name.startswith('.') or path.name.lower().endswith(ignored)): continue
        matches.append(path)
    details['total_matches']=len(matches)
    if not matches:return result('critical',f'{name}: Kein Backup gefunden',details,start)
    now=time.time(); newest=max(matches,key=lambda x:x.stat().st_mtime); st=newest.stat(); age=max(0.0,(now-st.st_mtime)/3600); size=st.st_size/1048576
    days=float(p.get('retention_days',7) or 0); recent=[x for x in matches if not days or now-x.stat().st_mtime<=days*86400]
    details.update(newest=str(newest),age_hours=round(age,2),size_bytes=st.st_size,size_mb=round(size,2),recent_count=len(recent),retention_days=days)
    minimum_size=float(p.get('minimum_size_mb',1) or 0)
    if minimum_size and size<minimum_size:return result('critical',f'{name}: Neuestes Backup ist mit {size:.1f} MB kleiner als {minimum_size:g} MB',details,start)
    minimum_count=int(p.get('minimum_count',1) or 1)
    if len(recent)<minimum_count:return result('critical',f'{name}: Nur {len(recent)} von mindestens {minimum_count} Backups im Prüfzeitraum vorhanden',details,start)
    cr=float(p.get('critical_age_hours',48) or 0); wr=float(p.get('warning_age_hours',26) or 0)
    if cr and age>=cr:return result('critical',f'{name}: Neuestes Backup ist {age:.1f} Stunden alt',details,start)
    if wr and age>=wr:return result('warning',f'{name}: Neuestes Backup ist {age:.1f} Stunden alt',details,start)
    return result('ok',f'{name}: Neuestes Backup ist {age:.1f} Stunden alt ({size:.1f} MB)',details,start)


def check_zfs_raid(p):
    start=time.monotonic(); name=p.get('name','ZFS / RAID'); mode=p.get('mode','zfs'); pool=str(p.get('pool','')).strip()
    if mode=='zfs':
        if not shutil.which('zpool'): return result('unknown',f'{name}: zpool ist nicht installiert',{},start)
        cmd=['zpool','status','-x']+([pool] if pool else [])
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=float(p.get('timeout',20) or 20))
        output=(proc.stdout+'\\n'+proc.stderr).strip(); details={'mode':mode,'pool':pool or None,'output':output}
        if proc.returncode!=0:return result('critical',f'{name}: ZFS-Prüfung fehlgeschlagen',details,start)
        normalized=' '.join(output.lower().split())
        healthy=(
            normalized == 'all pools are healthy'
            or normalized.endswith(' is healthy')
            or bool(re.search(r"(?:^|\s)pool\s+['\"]?.+?['\"]?\s+is\s+healthy(?:$|\s)",normalized))
        )
        details['normalized_output']=normalized
        details['healthy_detected']=healthy
        if not healthy:return result('critical',f'{name}: ZFS-Pool ist nicht gesund',details,start)
        return result('ok',f'{name}: ZFS-Pool ist gesund',details,start)
    path=Path('/proc/mdstat')
    if not path.exists():return result('unknown',f'{name}: /proc/mdstat fehlt',{},start)
    output=path.read_text(encoding='utf-8',errors='replace'); details={'mode':mode,'pool':pool or None,'output':output}
    relevant='\\n'.join(block for block in output.split('\\n\\n') if not pool or pool in block)
    if not relevant:return result('critical',f'{name}: MD-RAID {pool or ""} wurde nicht gefunden',details,start)
    if '_' in relevant or 'faulty' in relevant.lower() or 'inactive' in relevant.lower():return result('critical',f'{name}: MD-RAID ist degradiert',details,start)
    return result('ok',f'{name}: MD-RAID ist aktiv',details,start)

def check_package_updates(p):
    start=time.monotonic(); name=p.get('name','Updates'); count=None; manager=None; packages=[]
    try:
        if shutil.which('apt-get'):
            manager='apt'; proc=subprocess.run(['apt-get','-s','upgrade'],capture_output=True,text=True,timeout=float(p.get('timeout',60) or 60))
            for line in proc.stdout.splitlines():
                if not line.startswith('Inst '): continue
                parts=line.split()
                package=parts[1] if len(parts)>1 else line
                current=''; target=''
                match=re.search(r'\[([^\]]+)\]',line)
                if match: current=match.group(1)
                match=re.search(r'\(([^ )]+)',line)
                if match: target=match.group(1)
                packages.append({'name':package,'current':current,'target':target})
        elif shutil.which('checkupdates'):
            manager='pacman'; proc=subprocess.run(['checkupdates'],capture_output=True,text=True,timeout=float(p.get('timeout',60) or 60))
            for line in proc.stdout.splitlines():
                if not line.strip(): continue
                parts=line.split()
                packages.append({'name':parts[0],'current':parts[1] if len(parts)>1 else '','target':parts[3] if len(parts)>3 else ''})
        elif shutil.which('dnf'):
            manager='dnf'; proc=subprocess.run(['dnf','check-update','-q'],capture_output=True,text=True,timeout=float(p.get('timeout',60) or 60))
            for line in proc.stdout.splitlines():
                stripped=line.strip()
                if not stripped or stripped.startswith('Last metadata') or stripped.startswith('Obsoleting'): continue
                parts=stripped.split()
                if len(parts)>=2 and '.' in parts[0]:
                    packages.append({'name':parts[0],'current':'','target':parts[1]})
        else:return result('unknown',f'{name}: kein unterstützter Paketmanager gefunden',{},start)
    except Exception as e:return result('unknown',f'{name}: Update-Prüfung fehlgeschlagen: {e}',{'error':str(e)},start)
    count=len(packages)
    reboot=Path('/var/run/reboot-required').exists() or Path('/run/reboot-required').exists()
    details={'package_manager':manager,'updates':count,'packages':packages,'reboot_required':reboot,'suppress_retry_suffix':True}
    if reboot and p.get('reboot_is_critical',True):return result('critical',f'{name}: Neustart erforderlich, {count} Updates verfügbar',details,start)
    critical=int(p.get('critical_updates',30) or 30); warning=int(p.get('warning_updates',1) or 1)
    if count>=critical:return result('critical',f'{name}: {count} Updates verfügbar',details,start)
    if count>=warning or reboot:return result('warning',f'{name}: {count} Updates verfügbar'+(', Neustart erforderlich' if reboot else ''),details,start)
    return result('ok',f'{name}: System ist aktuell',details,start)


def _flatten_sensor_values(value, prefix=""):
    rows=[]
    if isinstance(value,dict):
        for key,item in value.items(): rows.extend(_flatten_sensor_values(item, f"{prefix}/{key}" if prefix else str(key)))
    elif isinstance(value,(int,float)):
        rows.append((prefix,float(value)))
    return rows

def check_hardware_sensors(p):
    start=time.monotonic(); name=p.get('name','Hardware-Sensoren'); mode=p.get('mode','auto')
    warning=float(p.get('warning_temperature',75) or 75); critical=float(p.get('critical_temperature',90) or 90); min_fan=float(p.get('minimum_fan_rpm',0) or 0)
    temperatures=[]; fans=[]; source=''
    try:
        if mode in ('auto','lm_sensors') and shutil.which('sensors'):
            source='lm-sensors'; cp=subprocess.run(['sensors','-j'],capture_output=True,text=True,timeout=float(p.get('timeout',15) or 15))
            data=json.loads(cp.stdout or '{}')
            for key,value in _flatten_sensor_values(data):
                lk=key.lower()
                if 'temp' in lk and ('input' in lk or lk.endswith('temp')): temperatures.append({'name':key,'value':value})
                if 'fan' in lk and ('input' in lk or lk.endswith('fan')): fans.append({'name':key,'value':value})
        elif mode in ('auto','ipmi') and shutil.which('ipmitool'):
            source='ipmi'; cp=subprocess.run(['ipmitool','sensor'],capture_output=True,text=True,timeout=float(p.get('timeout',15) or 15))
            for line in cp.stdout.splitlines():
                parts=[x.strip() for x in line.split('|')]
                if len(parts)<2: continue
                try: value=float(parts[1])
                except ValueError: continue
                unit=parts[2].lower() if len(parts)>2 else ''
                if 'degree' in unit or 'c' == unit: temperatures.append({'name':parts[0],'value':value})
                if 'rpm' in unit: fans.append({'name':parts[0],'value':value})
        else: return result('unknown',f'{name}: weder sensors noch ipmitool verfügbar',{'tools':tool_status()},start)
    except Exception as e: return result('unknown',f'{name}: Sensoren konnten nicht gelesen werden: {e}',{'error':str(e)},start)
    details={'source':source,'temperatures':temperatures,'fans':fans}
    hottest=max((x['value'] for x in temperatures),default=None); slowest=min((x['value'] for x in fans if x['value']>0),default=None)
    details.update(hottest_temperature=hottest,slowest_fan_rpm=slowest)
    if hottest is not None and hottest>=critical:return result('critical',f'{name}: Temperatur kritisch ({hottest:.1f} °C)',details,start)
    if hottest is not None and hottest>=warning:return result('warning',f'{name}: Temperatur erhöht ({hottest:.1f} °C)',details,start)
    if min_fan and slowest is not None and slowest<min_fan:return result('warning',f'{name}: Lüfterdrehzahl niedrig ({slowest:.0f} RPM)',details,start)
    return result('ok',f'{name}: Sensorwerte unauffällig'+(f', max. {hottest:.1f} °C' if hottest is not None else ''),details,start)

def check_pci_device(p):
    start=time.monotonic(); name=p.get('name','PCI-Gerät')
    if not shutil.which('lspci'): return result('unknown',f'{name}: lspci ist nicht installiert',{},start)
    cp=subprocess.run(['lspci','-nn'],capture_output=True,text=True,timeout=float(p.get('timeout',10) or 10)); lines=cp.stdout.splitlines()
    address=str(p.get('pci_address','')).lower().strip(); vendor=str(p.get('vendor_device','')).lower().strip(); desc=str(p.get('description_contains','')).lower().strip()
    matches=[line for line in lines if (not address or line.lower().startswith(address)) and (not vendor or vendor in line.lower()) and (not desc or desc in line.lower())]
    details={'matches':matches,'pci_address':address,'vendor_device':vendor,'description_contains':desc}
    if not matches:return result('critical',f'{name}: passendes PCI-Gerät wurde nicht gefunden',details,start)
    ptype=str(p.get('passthrough_type','none')); vmid=str(p.get('passthrough_vmid','')).strip()
    if ptype in ('qemu','lxc') and vmid:
        config=Path(f"/etc/pve/{'qemu-server' if ptype=='qemu' else 'lxc'}/{vmid}.conf")
        details['passthrough_config']=str(config)
        if not config.exists():return result('critical',f'{name}: Passthrough-Konfiguration fehlt',details,start)
        content=config.read_text(errors='replace').lower(); needles=[x for x in (address,vendor) if x]
        if not any(n in content for n in needles):return result('critical',f'{name}: PCI-Gerät ist nicht an {ptype.upper()} {vmid} durchgereicht',details,start)
        details['passthrough_detected']=True
    return result('ok',f'{name}: PCI-Gerät ist vorhanden',details,start)


def _command_lines(command, timeout=15):
    try:
        cp=subprocess.run(command,capture_output=True,text=True,timeout=timeout,check=False)
        return cp.returncode,cp.stdout.splitlines(),cp.stderr.strip()
    except Exception as e:return 127,[],str(e)

def check_hardware_inventory(p):
    start=time.monotonic(); details={'hostname':socket.gethostname(),'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'usb':[],'pci':[],'disks':[],'zfs_pools':[],'serial_by_id':[],'backup_files':[]}
    for item in glob.glob('/dev/serial/by-id/*'):
        details['serial_by_id'].append({'name':Path(item).name,'path':item,'target':os.path.realpath(item),'exists':Path(os.path.realpath(item)).exists()})
    serial_entries=[]
    for item in details['serial_by_id']:
        target=Path(item['target']).name
        props={}
        if shutil.which('udevadm'):
            rc,ulines,uerror=_command_lines(['udevadm','info','--query=property','--name',item['target']])
            for uline in ulines:
                if '=' in uline:
                    key,value=uline.split('=',1); props[key]=value
        # Resolve the concrete physical USB device behind this tty.  VID/PID
        # alone is not sufficient because many coordinators use the same
        # CP210x bridge (for example SONOFF Zigbee and Z-Wave sticks).
        usb_bus=''; usb_device=''; usb_sysfs=''
        try:
            node=(Path('/sys/class/tty')/target/'device').resolve()
            for parent in (node, *node.parents):
                if (parent/'idVendor').exists() and (parent/'idProduct').exists():
                    usb_sysfs=str(parent)
                    usb_bus=(parent/'busnum').read_text().strip() if (parent/'busnum').exists() else ''
                    usb_device=(parent/'devnum').read_text().strip() if (parent/'devnum').exists() else ''
                    break
        except Exception:
            pass
        serial_entries.append({
            'target':target,
            'path':item['path'],
            'name':item['name'],
            'vendor_id':str(props.get('ID_VENDOR_ID','')).lower(),
            'product_id':str(props.get('ID_MODEL_ID','')).lower(),
            'vendor':props.get('ID_VENDOR_FROM_DATABASE') or props.get('ID_VENDOR') or '',
            'model':props.get('ID_MODEL_FROM_DATABASE') or str(props.get('ID_MODEL','')).replace('_',' '),
            'serial':props.get('ID_SERIAL_SHORT') or props.get('ID_SERIAL') or '',
            'driver':props.get('ID_USB_DRIVER') or '',
            'bus':usb_bus,
            'device':usb_device,
            'usb_sysfs':usb_sysfs,
        })
    known_usb={
        ('10c4','ea60'):'USB-Seriell-Gerät (CP210x; z. B. SONOFF/ITead Zigbee oder Z-Wave)',
        ('1a86','7523'):'USB-Seriell-Gerät (CH340; häufig Zigbee-Koordinator)',
        ('0658','0200'):'Aeotec Z-Wave USB Stick',
        ('1cf1','0030'):'ConBee II Zigbee USB Gateway',
        ('0451','16a8'):'Texas Instruments Zigbee Coordinator',
    }
    rc,lines,error=_command_lines(['lsusb']) if shutil.which('lsusb') else (127,[],'lsusb fehlt')
    for line in lines:
        m=__import__('re').match(r'Bus (\d+) Device (\d+): ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4}) (.*)',line)
        if not m: continue
        vid,pid=m.group(3).lower(),m.group(4).lower()
        usb={'bus':m.group(1),'device':m.group(2),'vendor_id':vid,'product_id':pid,'description':m.group(5).strip()}
        same_id=[entry for entry in serial_entries if entry['vendor_id']==vid and entry['product_id']==pid]
        # Prefer exact bus/device matching.  Fall back to VID/PID only when it
        # is genuinely unique, never to the first of several equal devices.
        candidates=[entry for entry in same_id if str(entry.get('bus','')).lstrip('0')==str(int(m.group(1))) and str(entry.get('device','')).lstrip('0')==str(int(m.group(2)))]
        if not candidates and len(same_id)==1:
            candidates=same_id
        if len(candidates)==1:
            chosen=candidates[0]
            usb.update({
                'serial_path':chosen['path'],
                'device_path':'/dev/'+chosen['target'],
                'serial_number':chosen['serial'],
                'driver':chosen['driver'],
                'vendor_name':chosen['vendor'],
                'model_name':chosen['model'],
                'usb_sysfs':chosen.get('usb_sysfs',''),
            })
        elif same_id:
            usb['serial_candidates']=same_id
        best=(usb.get('model_name') or '').strip()
        if best and best.lower() not in {'cp2102 usb to uart bridge controller','cp210x uart bridge'}:
            usb['display_name']=best
        elif len(candidates)==1 and candidates[0].get('name'):
            by_id=candidates[0]['name'].replace('usb-','').split('-if00')[0].replace('_',' ')
            usb['display_name']=by_id
        else:
            usb['display_name']=known_usb.get((vid,pid),usb['description'])
        usb['identification_quality']='exact' if usb.get('serial_path') and usb.get('model_name') else ('probable' if (vid,pid) in known_usb else 'generic')
        details['usb'].append(usb)
    if error: details['usb_error']=error
    rc,lines,error=_command_lines(['lspci','-nn']) if shutil.which('lspci') else (127,[],'lspci fehlt')
    for line in lines:
        address=line.split(' ',1)[0] if ' ' in line else ''
        ids=__import__('re').findall(r'\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]',line)
        details['pci'].append({'address':address,'description':line[len(address):].strip(),'vendor_id':ids[-1][0].lower() if ids else '','device_id':ids[-1][1].lower() if ids else ''})
    if error: details['pci_error']=error
    rc,lines,error=_command_lines(['lsblk','-J','-b','-o','NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,MOUNTPOINTS']) if shutil.which('lsblk') else (127,[],'lsblk fehlt')
    if lines:
        try:
            tree=json.loads('\n'.join(lines))
            def walk(items):
                for x in items or []:
                    if x.get('type')=='disk': details['disks'].append({k:x.get(k) for k in ('name','path','type','size','model','serial','tran','rota','mountpoints')})
                    walk(x.get('children'))
            walk(tree.get('blockdevices'))
        except Exception as e: details['lsblk_error']=str(e)
    if error: details['lsblk_error']=error
    if shutil.which('zpool'):
        rc,lines,error=_command_lines(['zpool','list','-H','-o','name,size,alloc,free,health'])
        for line in lines:
            parts=line.split('\t')
            if len(parts)>=5: details['zfs_pools'].append(dict(zip(('name','size','allocated','free','health'),parts[:5])))
        if error: details['zfs_error']=error
    patterns=p.get('backup_patterns') or ['/var/lib/vz/dump/*','/mnt/*/dump/*','/mnt/*/backup/*']
    for pattern in patterns[:20]:
        for raw in glob.glob(str(pattern))[:200]:
            path=Path(raw)
            try:
                if path.is_file():
                    st=path.stat(); details['backup_files'].append({'path':str(path),'size_bytes':st.st_size,'modified':time.strftime('%Y-%m-%dT%H:%M:%S%z',time.localtime(st.st_mtime))})
            except OSError: pass
    details['backup_files']=sorted(details['backup_files'],key=lambda x:x['modified'],reverse=True)[:200]
    counts={k:len(details[k]) for k in ('usb','pci','disks','zfs_pools','serial_by_id','backup_files')}
    details['counts']=counts
    return result('ok',f"Hardwareinventar: {counts['disks']} Datenträger, {counts['usb']} USB, {counts['pci']} PCI, {counts['zfs_pools']} ZFS-Pools",details,start)

def download_bytes(url,insecure=False,timeout=30):
    context=ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(url,timeout=timeout,context=context) as response:
        return response.read()

def action_result(status,message,details,start,post_action=None):
    payload=result(status,message,details,start)
    if post_action: payload['_post_action']=post_action
    return payload

def execute_action(task):
    start=time.monotonic()
    action=str(task.get('action_type',''))
    params=task.get('parameters') or {}
    config=cfg()
    permissions={**DEFAULT_ACTION_PERMISSIONS,**(config.get('action_permissions') or {})}
    if action not in permissions or not permissions.get(action):
        return action_result('critical',f'Aktion {action} ist lokal nicht freigegeben',{'action':action},start)
    try:
        if action=='refresh_inventory':
            return check_hardware_inventory({'name':'Hardwareinventar'})
        if action=='run_diagnostics':
            details={
                'identity':identity(),
                'config_file':str(CONFIG),
                'config_readable':CONFIG.is_file(),
                'agent_path':str(AGENT_PATH),
                'agent_writable':os.access(AGENT_PATH,os.W_OK),
                'backup_directory':str(BACKUP_DIR),
                'tools':tool_status(),
                'service':{},
            }
            if shutil.which('systemctl'):
                cp=subprocess.run(['systemctl','show','miniguard.service','--property=ActiveState,SubState,NRestarts,ExecMainStatus'],capture_output=True,text=True,timeout=10)
                details['service']={k:v for line in cp.stdout.splitlines() if '=' in line for k,v in [line.split('=',1)]}
            return action_result('ok','MiniGuard-Diagnose abgeschlossen',details,start)
        if action=='fetch_logs':
            lines=max(20,min(int(params.get('lines',200) or 200),1000))
            if shutil.which('journalctl'):
                invocation_id=''
                if shutil.which('systemctl'):
                    invocation=subprocess.run(
                        ['systemctl','show','miniguard.service','--property=InvocationID','--value'],
                        capture_output=True,text=True,timeout=10,
                    )
                    candidate=(invocation.stdout or '').strip()
                    if re.fullmatch(r'[0-9a-fA-F]{32}',candidate):
                        invocation_id=candidate.lower()
                command=['journalctl']
                if invocation_id:
                    command.append(f'_SYSTEMD_INVOCATION_ID={invocation_id}')
                else:
                    command.extend(['-u','miniguard.service','-b'])
                command.extend(['-n',str(lines),'--no-pager','-o','short-iso'])
                cp=subprocess.run(command,capture_output=True,text=True,timeout=20)
                output=(cp.stdout or cp.stderr)[-100000:]
                scope='current_invocation' if invocation_id else 'current_boot'
            else:
                output='journalctl ist nicht verfügbar.'
                invocation_id=''
                scope='unavailable'
            return action_result(
                'ok',
                f'{lines} MiniGuard-Protokollzeilen der aktuellen Dienstinstanz abgerufen',
                {'logs':output,'lines':lines,'scope':scope,'invocation_id':invocation_id},
                start,
            )
        if action=='check_tool':
            tool=str(params.get('tool','')).strip()
            if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}',tool):
                return action_result('critical','Ungültiger Werkzeugname',{'tool':tool},start)
            path=shutil.which(tool)
            return action_result('ok' if path else 'warning',f'{tool} ist '+('verfügbar' if path else 'nicht verfügbar'),{'tool':tool,'path':path},start)
        if action=='sync_permissions':
            requested=params.get('permissions') or {}
            config['action_permissions']={name:bool(requested.get(name,DEFAULT_ACTION_PERMISSIONS[name])) for name in DEFAULT_ACTION_PERMISSIONS}
            save_cfg(config)
            return action_result('ok','MiniGuard-Berechtigungen wurden aktualisiert',{'permissions':config['action_permissions']},start)
        if action=='rotate_token':
            new_token=str(params.get('new_token',''))
            if len(new_token)<32:
                return action_result('critical','Neues Agent-Token ist ungültig',{},start)
            return action_result('ok','Agent-Token wurde rotiert',{'token_rotated':True},start,{'type':'rotate_token','new_token':new_token})
        if action=='update_agent':
            url=str(params.get('url','')).strip()
            expected=str(params.get('sha256','')).lower().strip()
            if not url.startswith(config['lanaxy'].rstrip('/')+'/miniguard/'):
                return action_result('critical','Update-URL gehört nicht zur registrierten LANaxy-Instanz',{'url':url},start)
            payload=download_bytes(url,bool(config.get('insecure')),60)
            actual=hashlib.sha256(payload).hexdigest()
            if not expected or actual!=expected:
                return action_result('critical','MiniGuard-Update hat eine ungültige Prüfsumme',{'expected':expected,'actual':actual},start)
            compile(payload.decode('utf-8'),'<miniguard-update>','exec')
            BACKUP_DIR.mkdir(parents=True,exist_ok=True)
            backup=BACKUP_DIR/f"miniguard-{VERSION}-{int(time.time())}"
            if AGENT_PATH.exists(): shutil.copy2(AGENT_PATH,backup)
            temp=AGENT_PATH.with_suffix('.new')
            temp.write_bytes(payload); os.chmod(temp,0o755); os.replace(temp,AGENT_PATH)
            return action_result('ok','MiniGuard wurde aktualisiert und wird neu gestartet',{'old_version':VERSION,'sha256':actual,'backup':str(backup)},start,{'type':'restart_agent'})
        if action=='rollback_agent':
            backups=sorted(BACKUP_DIR.glob('miniguard-*'),key=lambda item:item.stat().st_mtime,reverse=True)
            if not backups:
                return action_result('critical','Keine MiniGuard-Sicherung für ein Rollback vorhanden',{},start)
            payload=backups[0].read_bytes()
            compile(payload.decode('utf-8'),'<miniguard-rollback>','exec')
            temp=AGENT_PATH.with_suffix('.rollback')
            temp.write_bytes(payload); os.chmod(temp,0o755); os.replace(temp,AGENT_PATH)
            return action_result('ok','MiniGuard-Rollback wurde eingespielt',{'backup':str(backups[0])},start,{'type':'restart_agent'})
        if action=='restart_agent':
            return action_result('ok','MiniGuard wird neu gestartet',{},start,{'type':'restart_agent'})
        if action=='restart_host':
            return action_result('ok','Host-Neustart wurde für eine Minute später geplant',{},start,{'type':'restart_host'})
        return action_result('critical',f'Nicht unterstützte Aktion: {action}',{},start)
    except Exception as error:
        return action_result('critical',f'MiniGuard-Aktion fehlgeschlagen: {error}',{'action':action,'exception':type(error).__name__},start)

CHECKS={'system_info':check_system_info,'smart':check_smart,'systemd':check_systemd,'storage':check_storage,'usb':check_usb,'system_load':check_system_load,'file_age':check_file_age,'docker':check_docker,'network_share':check_network_share,'backup':check_backup,'zfs_raid':check_zfs_raid,'package_updates':check_package_updates,'hardware_sensors':check_hardware_sensors,'pci_device':check_pci_device,'hardware_inventory':check_hardware_inventory}
def execute(task):
    if task.get('task_kind')=='action':
        return execute_action(task)
    start=time.monotonic(); ct=task.get('check_type'); fn=CHECKS.get(ct)
    if not fn:return result('unknown',f'Nicht unterstützter Check: {ct}',{},start,'unsupported_check')
    try:return fn(task.get('parameters') or {})
    except Exception as e:return result('unknown',f'MiniGuard-Check fehlgeschlagen: {e}',{'exception':type(e).__name__},start,'check_exception')

def daemon():
    c=cfg(); last_heartbeat=0
    while True:
        now=time.monotonic()
        try:
            if now-last_heartbeat>=30:
                heartbeat_once(c); last_heartbeat=now
            task=request_json(c['lanaxy']+f"/api/miniguards/{c['agent_id']}/checks/next",{},c['token'],bool(c.get('insecure')),10)
            if task.get('id'):
                out=execute(task)
                post_action=out.pop('_post_action',None)
                request_json(c['lanaxy']+f"/api/miniguards/{c['agent_id']}/checks/{task['id']}/result",out,c['token'],bool(c.get('insecure')),30)
                if post_action:
                    if post_action.get('type')=='rotate_token':
                        c['token']=post_action['new_token']; c['queue_failures']=0; c['last_error']=''; save_cfg(c)
                    elif post_action.get('type')=='restart_host':
                        subprocess.Popen(['shutdown','-r','+1','LANaxy MiniGuard: bestätigter Host-Neustart'])
                    elif post_action.get('type')=='restart_agent':
                        return
            if c.get('queue_failures') or c.get('last_error'):
                c['queue_failures']=0; c['last_error']=''; save_cfg(c)
        except Exception as e:
            c['queue_failures']=int(c.get('queue_failures',0) or 0)+1
            c['last_error']=str(e)[:500]
            try: save_cfg(c)
            except Exception: pass
            print(f'MiniGuard-Kommunikation fehlgeschlagen: {e}',file=sys.stderr)
        time.sleep(0.5)

def uninstall():
    os.system('systemctl disable --now miniguard.service >/dev/null 2>&1 || true')
    for path in [Path('/etc/systemd/system/miniguard.service'),Path('/usr/local/bin/miniguard')]:
        try:path.unlink()
        except FileNotFoundError:pass
    if CONFIG.parent.exists():shutil.rmtree(CONFIG.parent)
    os.system('systemctl daemon-reload >/dev/null 2>&1 || true'); print('MiniGuard wurde deinstalliert.')
def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True); r=sub.add_parser('register'); r.add_argument('--lanaxy',required=True); r.add_argument('--agent-id',required=True); r.add_argument('--code',required=True); r.add_argument('--insecure',action='store_true'); sub.add_parser('heartbeat'); sub.add_parser('daemon'); sub.add_parser('uninstall'); a=p.parse_args()
    {'register':lambda:register(a),'heartbeat':lambda:print(json.dumps(heartbeat_once(),ensure_ascii=False)),'daemon':daemon,'uninstall':uninstall}[a.cmd]()
if __name__=='__main__':
    try:main()
    except RuntimeError as e:print(f'MiniGuard: {e}',file=sys.stderr); raise SystemExit(1)
    except KeyboardInterrupt:raise SystemExit(130)
