import sqlite3,json
from pathlib import Path
from datetime import datetime,timezone
class Database:
 def __init__(self,p=Path('data/userbot.db')):p.parent.mkdir(exist_ok=True);self.p=p;self.init()
 def c(self):x=sqlite3.connect(self.p,timeout=30);x.row_factory=sqlite3.Row;return x
 def init(self):
  with self.c() as x:x.executescript('''CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,source TEXT UNIQUE,enabled INTEGER DEFAULT 1,target_count INTEGER DEFAULT 100,per_file INTEGER DEFAULT 20,output_chat TEXT DEFAULT '',created_at TEXT);CREATE TABLE IF NOT EXISTS fingerprints(fingerprint TEXT PRIMARY KEY,source TEXT,message_id INTEGER,created_at TEXT);CREATE TABLE IF NOT EXISTS quizzes(id INTEGER PRIMARY KEY,fingerprint TEXT UNIQUE,source TEXT,message_id INTEGER,question TEXT,options_json TEXT,correct_index INTEGER,confidence REAL,explanation TEXT,raw_json TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,user_id TEXT,data_json TEXT,status TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,level TEXT,message TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),status TEXT,detail TEXT,updated_at TEXT);''')
 def sources(self):
  with self.c() as x:return [dict(r) for r in x.execute('select * from sources order by id desc')]
 def add_source(self,s,n=100,pf=20,out=''):
  with self.c() as x:x.execute('insert into sources(source,target_count,per_file,output_chat,created_at) values(?,?,?,?,?) on conflict(source) do update set target_count=excluded.target_count,per_file=excluded.per_file,output_chat=excluded.output_chat',(s,n,pf,out,datetime.now(timezone.utc).isoformat()))
 def fp(self,f):
  with self.c() as x:return x.execute('select 1 from fingerprints where fingerprint=?',(f,)).fetchone() is not None
 def savefp(self,f,s,m):
  with self.c() as x:x.execute('insert or ignore into fingerprints values(?,?,?,?)',(f,s,m,datetime.now(timezone.utc).isoformat()))
 def save(self,q):
  with self.c() as x:x.execute('insert or ignore into quizzes(fingerprint,source,message_id,question,options_json,correct_index,confidence,explanation,raw_json,created_at) values(?,?,?,?,?,?,?,?,?,?)',(q['fingerprint'],q['source'],q['message_id'],q['question'],json.dumps(q['options'],ensure_ascii=False),q['correct_index'],q['confidence'],q.get('explanation',''),json.dumps(q,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
 def quizzes(self,source=None):
  with self.c() as x:return [dict(r) for r in x.execute('select * from quizzes'+(' where source=?' if source else '')+' order by id',((source,) if source else ())) ]
 def log(self,l,m):
  with self.c() as x:x.execute('insert into logs(level,message,created_at) values(?,?,?)',(l,str(m),datetime.now(timezone.utc).isoformat()))
 def logs(self):
  with self.c() as x:return '\n'.join(f"[{r[0]}] {r[1]}: {r[2]}" for r in x.execute('select created_at,level,message from logs order by id desc limit 1000'))
 def hb(self,s,d=''):
  with self.c() as x:x.execute('insert into heartbeat(id,status,detail,updated_at) values(1,?,?,?) on conflict(id) do update set status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at',(s,d,datetime.now(timezone.utc).isoformat()))
 def heartbeat(self):
  with self.c() as x:r=x.execute('select * from heartbeat').fetchone();return dict(r) if r else None
 def count(self,t):
  with self.c() as x:return x.execute(f'select count(*) from {t}').fetchone()[0]
