from guardians.base import BaseGuardian
from miniguard_manager import get_agent
class Guardian(BaseGuardian):
    GUARDIAN={'id':'miniguard_inventory','name':'MiniGuard Inventar Guardian','version':'1.0.0','description':'Meldet unbestätigte Hardwareänderungen eines MiniGuards','icon':'inventory','category':'Hardware','service_family':'miniguard','internal':True}
    CONFIG_SCHEMA={
      'name':{'type':'text','label':'Name','required':True},'id':{'type':'slug','label':'Guardian-ID'},
      'miniguard_id':{'type':'select','label':'MiniGuard','required':True,'options':[]},
      'removed_is_critical':{'type':'checkbox','label':'Entfernte Hardware ist Critical','default':True},
      'interval':{'type':'number','label':'Intervall (Sekunden)','default':60,'min':30},'timeout':{'type':'number','label':'Timeout (Sekunden)','default':5,'min':1},'retries':{'type':'number','label':'Fehlversuche bis Critical','default':1,'min':1}}
    REQUIRED=('miniguard_id',)
    def run(self):
      agent=get_agent(str(self.check.get('miniguard_id','')))
      if not agent:return self.critical(f'{self.name}: MiniGuard nicht gefunden')
      pending=[c for c in agent.get('inventory_changes',[]) if not c.get('acknowledged_at')]
      details={'changes':pending,'inventory_updated_at':agent.get('inventory_updated_at')}
      if not pending:return self.ok(f'{self.name}: Keine unbestätigten Hardwareänderungen',details=details)
      removed=sum(1 for c in pending if c.get('change')=='removed'); added=sum(1 for c in pending if c.get('change')=='added'); changed=sum(1 for c in pending if c.get('change')=='changed')
      message=f'{self.name}: {len(pending)} Hardwareänderungen ({added} neu, {removed} entfernt, {changed} geändert)'
      if removed and self.check.get('removed_is_critical',True):return self.critical(message,details=details)
      return self.warning(message,details=details)
