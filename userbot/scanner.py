import re,hashlib,json,asyncio
from telethon import functions
from ai.operator import Operator
URL=re.compile(r'(?:https?://|t\.me/|telegram\.me/)[^\s]+|(?<!\w)@[A-Za-z0-9_]{3,}',re.I)
def clean(s):return re.sub(r'\s+',' ',URL.sub('',str(s or ''))).strip(' -|•')
def fingerprint(q,o):return hashlib.sha256(json.dumps({'q':clean(q).lower(),'o':[clean(x).lower() for x in o]},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def pdata(msg):
 p=getattr(msg,'poll',None)
 if not p or not getattr(p,'quiz',False):return None
 q=getattr(getattr(p,'question',''),'text',str(getattr(p,'question','')))
 o=[clean(getattr(getattr(a,'text',''),'text',str(getattr(a,'text','')))) for a in getattr(p,'answers',[]) or []]
 return clean(q),[x for x in o if x],p
async def native(client,src,msg,p):
 results=getattr(getattr(msg,'poll',None),'results',None)
 items=getattr(results,'results',None) if results else None
 for r in items or []:
  if getattr(r,'correct',False):
   try:return list(items).index(r)
   except ValueError: pass
 try:
  await client(functions.messages.GetPollResults(peer=await client.get_input_entity(src),msg_id=msg.id,poll_hash=getattr(p,'hash',0)))
 except Exception:
  pass
 return None
async def scan(client,db,src,target,stop,settings,stats):
 op=Operator();found=0;checked=0
 async for msg in client.iter_messages(src,limit=None):
  if stop.is_set():break
  checked+=1;d=pdata(msg)
  if not d:continue
  q,o,p=d
  if len(o)<2:continue
  f=fingerprint(q,o)
  if db.fp(f):continue
  ci=await native(client,src,msg,p);conf=1.0 if ci is not None else 0;exp=''
  if ci is None and settings.quiz_ai_fallback:
   try:ci,conf,exp=op.solve(q,o)
   except Exception as e:db.log('ERROR',e);ci=None
  if ci is None or conf<settings.quiz_ai_min_confidence:db.log('WARN',f'Skipped low confidence {conf:.2f}: {q[:80]}');continue
  db.savefp(f,src,msg.id);db.save({'fingerprint':f,'source':str(src),'message_id':msg.id,'question':q,'options':o,'correct_index':ci,'confidence':conf,'explanation':exp});found+=1;stats.update(found=found,checked=checked,source=str(src))
  if target and found>=target:break
  await asyncio.sleep(0.8)
 return found
