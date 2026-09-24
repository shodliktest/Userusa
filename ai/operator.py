from pathlib import Path
from ai.groq_pool import GroqPool
class Operator:
 def __init__(self):self.pool=GroqPool()
 def reply(self,h,t):
  m=[{'role':'system','content':Path('config/agent_prompt.txt').read_text(encoding='utf-8')}];m+=h[-14:];m.append({'role':'user','content':t});return self.pool.chat(m,.35)
 def solve(self,q,opts):
  nums='\n'.join(f'{i+1}. {x}' for i,x in enumerate(opts));sys='Return ONLY JSON. Solve accurately. If uncertain confidence must be <0.78. explanation in Uzbek.';u=f'Savol:\n{q}\n\nVariantlar:\n{nums}\nJSON: {{"correct_index":0,"confidence":0.0,"explanation":""}}';o=self.pool.json(self.pool.chat([{'role':'system','content':sys},{'role':'user','content':u}],.05));return int(o.get('correct_index',-1)),float(o.get('confidence',0)),str(o.get('explanation','')).strip()
