import threading
from custom_portals import resolve_portal_class

class PortalManager:
 def __init__(self, command_handler, token_validator):
  self.command_handler=command_handler; self.token_validator=token_validator
  self.instances={}; self.lock=threading.RLock()
 def start(self, config):
  self.stop()
  for item in config.get("control",{}).get("portals",[]):
   if not item.get("enabled",True): continue
   portal=None
   try:
    cls=resolve_portal_class(item["type"])
    portal=cls(item,self.command_handler,self.token_validator)
    self.instances[item["id"]]=portal
    if getattr(cls,"BACKGROUND",False): portal.start()
    else: portal.running=True
   except Exception as error:
    if portal is not None:
     portal.running=False
     portal.last_error=str(error)
    continue
 def stop(self):
  with self.lock:
   for portal in self.instances.values():
    try: portal.stop()
    except Exception: pass
   self.instances={}
 def status(self):
  return {key:value.health() for key,value in self.instances.items()}
