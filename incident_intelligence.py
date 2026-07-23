from __future__ import annotations
from collections import deque

def dependency_graph(checks): return {str(c.get('id')):[str(x) for x in c.get('depends_on',[]) if x] for c in checks}
def ancestors(graph,node):
    out=[]; seen=set(); q=deque([(node,0)])
    while q:
        current,depth=q.popleft()
        for parent in graph.get(current,[]):
            if parent in seen: continue
            seen.add(parent); out.append((parent,depth+1)); q.append((parent,depth+1))
    return out
def analyze_root_causes(checks,state,guardian_id):
    graph=dependency_graph(checks); by_id={str(c.get('id')):c for c in checks}; candidates=[]
    for parent,depth in ancestors(graph,guardian_id):
        status=str((state.get(parent) or {}).get('status','unknown'))
        score=(100-depth*10)+(30 if status=='critical' else 15 if status=='warning' else 0)
        candidates.append({'guardian_id':parent,'guardian_name':by_id.get(parent,{}).get('name',parent),'status':status,'depth':depth,'score':score,'reason':'Direkte ausgefallene Abhängigkeit' if depth==1 else 'Übergeordnete Abhängigkeit'})
    return sorted(candidates,key=lambda x:(-x['score'],x['depth'],x['guardian_name']))
def incident_signature(checks,guardian_id):
    graph=dependency_graph(checks); chain=[x for x,_ in ancestors(graph,guardian_id)]; return '|'.join(sorted([guardian_id,*chain]))
