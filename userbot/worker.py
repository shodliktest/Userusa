import asyncio,threading
from telethon import TelegramClient,events
from telethon.sessions import StringSession
from config.settings import load_settings
from storage.database import Database
from ai.operator import Operator
from userbot.scanner import scan
class Worker:
 def __init__(self):self.s=load_settings();self.db=Database();self.loop=None;self.client=None;self.thread=None;self.running=False;self.scanning=False;self.stop=threading.Event();self.stats={};self.hist={}
 def start(self):
  if self.thread and self.thread.is_alive():return
  self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def run(self):
  self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
  try:self.loop.run_until_complete(self.main())
  except Exception as e:self.db.hb('error',str(e));self.db.log('ERROR',e)
 async def main(self):
  self.client=TelegramClient(StringSession(self.s.session_string),self.s.api_id,self.s.api_hash);await self.client.connect()
  if not await self.client.is_user_authorized():self.db.hb('error','Session authorized emas');return
  op=Operator();self.running=True;self.db.hb('running','Telegram ulangan')
  @self.client.on(events.NewMessage(incoming=True))
  async def incoming(e):
   if not e.is_private:return
   t=(e.raw_text or '').strip()
   if not t:return
   try:
    h=self.hist.setdefault(str(e.sender_id),[]);a=op.reply(h,t);h += [{'role':'user','content':t},{'role':'assistant','content':a}];del h[:-14];await e.reply(a)
   except Exception as x:self.db.log('ERROR',x)
  await self.client.run_until_disconnected()
 def start_scan(self,rows):
  if self.scanning:return False
  self.stop.clear();self.scanning=True
  def job():
   async def go():
    try:
     for r in rows:
      if self.stop.is_set():break
      self.db.log('INFO',f"Scan: {r['source']} target={r['target_count']}");n=await scan(self.client,self.db,r['source'],r['target_count'],self.stop,self.s,self.stats);self.db.log('INFO',f"Done {r['source']}: {n}")
    except Exception as e:self.db.log('ERROR',f'Scanner: {e}')
    finally:self.scanning=False
   asyncio.run_coroutine_threadsafe(go(),self.loop).result()
  threading.Thread(target=job,daemon=True).start();return True
 def stop_scan(self):self.stop.set()
W=None

def get_worker():
 global W
 if W is None:W=Worker()
 return W
def ensure_worker_started():get_worker().start();return True
def worker_is_alive():w=get_worker();return bool(w.thread and w.thread.is_alive() and w.running)
