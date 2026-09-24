import json,re,time,threading
from groq import Groq
from config.settings import load_settings
class GroqPool:
 def __init__(self):
  s=load_settings();self.keys=s.groq_keys;self.model=s.groq_model;self.cool=[0.0]*len(self.keys);self.i=0;self.lock=threading.Lock()
 def pick(self):
  now=time.time()
  with self.lock:
   for _ in range(len(self.keys)):
    i=self.i%len(self.keys);self.i=(self.i+1)%len(self.keys)
    if self.cool[i]<=now:return i
  return None
 def chat(self,messages,temperature=.2):
  if not self.keys:raise RuntimeError('Groq API key topilmadi')
  last=None
  for _ in range(max(10,len(self.keys))):
   i=self.pick()
   if i is None:time.sleep(.5);continue
   try:return Groq(api_key=self.keys[i]).chat.completions.create(model=self.model,messages=messages,temperature=temperature).choices[0].message.content
   except Exception as e:
    last=e;code=getattr(e,'status_code',None);m=str(e).lower()
    self.cool[i]=time.time()+(30 if code==429 or 'rate limit' in m or 'too many requests' in m else 3600 if code in (401,403) or 'invalid api key' in m else 10)
  raise RuntimeError(f'Groq key pool ishlamadi: {last}')
 def json(self,s):
  s=s.strip().replace('```json','').replace('```','').strip()
  try:return json.loads(s)
  except: 
   m=re.search(r'\{.*\}',s,re.S)
   if m:return json.loads(m.group())
   raise
