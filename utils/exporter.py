import re
from pathlib import Path
def safe(s):return re.sub(r'\s+',' ',re.sub(r'[\\/:*?"<>|]+',' ',str(s))).strip()[:90] or 'test'
def export(quizzes,n=20,name='test'):
 out=[]
 for k in range(0,len(quizzes),n):
  lines=[]
  for i,q in enumerate(quizzes[k:k+n],1):
   lines.append(f"{i}. {q['question'].strip()}")
   for j,o in enumerate(__import__('json').loads(q['options_json']) if isinstance(q.get('options_json'),str) else q['options']):lines.append(f"{'*' if j==q['correct_index'] else ''}{chr(65+j)}) {o.strip()}")
   if q.get('explanation'):lines.append('Izoh: '+q['explanation'].strip())
   lines.append('')
  p=Path('exports')/f'{safe(name)}_{k//n+1:02d}.txt';p.write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8');out.append(p)
 return out
