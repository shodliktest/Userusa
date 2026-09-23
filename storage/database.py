import sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime

DB_PATH=Path("data/userbot.db")

class Database:
    def __init__(self,path=DB_PATH):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.path=path
        self._init()

    def conn(self): return sqlite3.connect(self.path)

    def _init(self):
        with self.conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS sources(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT UNIQUE,
                enabled INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS fingerprints(
                fingerprint TEXT PRIMARY KEY,
                source TEXT,
                message_id INTEGER,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS quizzes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE,
                source TEXT,
                message_id INTEGER,
                question TEXT,
                options_json TEXT,
                correct_index INTEGER,
                raw_json TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                data_json TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                message TEXT,
                created_at TEXT
            );
            """)

    def add_source(self,source):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO sources(source,created_at) VALUES(?,?)",
                      (source,datetime.utcnow().isoformat()))

    def list_sources(self):
        with self.conn() as c:
            rows=c.execute("SELECT source,enabled,created_at FROM sources ORDER BY id DESC").fetchall()
        return [{"source":r[0],"enabled":bool(r[1]),"created_at":r[2]} for r in rows]

    def fingerprint_exists(self,fp):
        with self.conn() as c: return c.execute("SELECT 1 FROM fingerprints WHERE fingerprint=?",(fp,)).fetchone() is not None

    def save_fingerprint(self,fp,source,message_id):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO fingerprints VALUES(?,?,?,?)",
                      (fp,source,message_id,datetime.utcnow().isoformat()))

    def save_quiz(self,q):
        fp=q["fingerprint"]
        with self.conn() as c:
            c.execute("""INSERT OR IGNORE INTO quizzes
            (fingerprint,source,message_id,question,options_json,correct_index,raw_json,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (fp,q.get("source"),q.get("message_id"),q["question"],
             json.dumps(q["options"],ensure_ascii=False),q["correct_index"],
             json.dumps(q,ensure_ascii=False),datetime.utcnow().isoformat()))

    def count_quizzes(self):
        with self.conn() as c:return c.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0]
    def count_fingerprints(self):
        with self.conn() as c:return c.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
    def count_orders(self):
        with self.conn() as c:return c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def add_log(self,level,message):
        with self.conn() as c:
            c.execute("INSERT INTO logs(level,message,created_at) VALUES(?,?,?)",
                      (level,message,datetime.utcnow().isoformat()))

    def get_logs(self):
        with self.conn() as c:
            rows=c.execute("SELECT created_at,level,message FROM logs ORDER BY id DESC LIMIT 500").fetchall()
        return "\n".join(f"[{a}] {b}: {d}" for a,b,d in rows)

    def export_quizzes(self,fmt):
        Path("exports").mkdir(exist_ok=True)
        with self.conn() as c:
            rows=c.execute("SELECT question,options_json,correct_index FROM quizzes ORDER BY id").fetchall()
        if not rows:return None
        if fmt=="json":
            out=[{"question":q,"options":json.loads(o),"correct_index":i} for q,o,i in rows]
            p=Path("exports/quizzes.json"); p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
        else:
            lines=[]
            for n,(q,o,i) in enumerate(rows,1):
                opts=json.loads(o)
                lines.append(f"{n}. {q}")
                for j,opt in enumerate(opts):
                    mark="*" if j==i else ""
                    lines.append(f"{mark}{chr(65+j)}) {opt}")
                lines.append("")
            p=Path("exports/quizzes.txt"); p.write_text("\n".join(lines),encoding="utf-8")
        return p
