import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, p=Path('data/userbot.db')):
        p.parent.mkdir(parents=True, exist_ok=True)
        self.p = p
        self.init()

    def c(self):
        x = sqlite3.connect(self.p, timeout=30)
        x.row_factory = sqlite3.Row
        return x

    def init(self):
        with self.c() as x:
            x.executescript('''
            CREATE TABLE IF NOT EXISTS sources(
                id INTEGER PRIMARY KEY,
                source TEXT UNIQUE,
                enabled INTEGER DEFAULT 1,
                target_count INTEGER DEFAULT 100,
                per_file INTEGER DEFAULT 20,
                output_chat TEXT DEFAULT '',
                publish_enabled INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS fingerprints(
                fingerprint TEXT PRIMARY KEY,
                source TEXT,
                message_id INTEGER,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS quizzes(
                id INTEGER PRIMARY KEY,
                fingerprint TEXT UNIQUE,
                source TEXT,
                message_id INTEGER,
                question TEXT,
                options_json TEXT,
                correct_index INTEGER,
                confidence REAL,
                explanation TEXT,
                answer_source TEXT DEFAULT '',
                voted_now INTEGER DEFAULT 0,
                raw_json TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,user_id TEXT,data_json TEXT,status TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,level TEXT,message TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),status TEXT,detail TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS scan_state(source TEXT PRIMARY KEY,last_message_id INTEGER DEFAULT 0,checked INTEGER DEFAULT 0,found INTEGER DEFAULT 0,updated_at TEXT);
            ''')
            # Safe migrations for databases created by earlier versions.
            cols = {r[1] for r in x.execute('PRAGMA table_info(sources)')}
            if 'publish_enabled' not in cols:
                x.execute('ALTER TABLE sources ADD COLUMN publish_enabled INTEGER DEFAULT 0')
            if 'enabled' not in cols:
                x.execute('ALTER TABLE sources ADD COLUMN enabled INTEGER DEFAULT 1')
            if 'answer_source' not in {r[1] for r in x.execute('PRAGMA table_info(quizzes)')}:
                x.execute("ALTER TABLE quizzes ADD COLUMN answer_source TEXT DEFAULT ''")
            if 'voted_now' not in {r[1] for r in x.execute('PRAGMA table_info(quizzes)')}:
                x.execute("ALTER TABLE quizzes ADD COLUMN voted_now INTEGER DEFAULT 0")

    def sources(self):
        with self.c() as x:
            return [dict(r) for r in x.execute('SELECT * FROM sources ORDER BY id DESC')]

    def add_source(self, s, n=100, pf=20, out='', publish_enabled=0):
        s = str(s).strip()
        with self.c() as x:
            x.execute('''INSERT INTO sources(source,target_count,per_file,output_chat,publish_enabled,created_at)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(source) DO UPDATE SET
                           target_count=excluded.target_count,
                           per_file=excluded.per_file,
                           output_chat=excluded.output_chat,
                           publish_enabled=excluded.publish_enabled,
                           enabled=1''',
                      (s, int(n), int(pf), str(out).strip(), int(bool(publish_enabled)), now()))

    def set_source_enabled(self, source, enabled):
        with self.c() as x:
            x.execute('UPDATE sources SET enabled=? WHERE source=?', (int(bool(enabled)), source))

    def fp(self, f):
        with self.c() as x:
            return x.execute('SELECT 1 FROM fingerprints WHERE fingerprint=?', (f,)).fetchone() is not None

    def savefp(self, f, s, m):
        with self.c() as x:
            x.execute('INSERT OR IGNORE INTO fingerprints VALUES(?,?,?,?)', (f, s, m, now()))

    def save(self, q):
        with self.c() as x:
            x.execute('''INSERT OR IGNORE INTO quizzes
                (fingerprint,source,message_id,question,options_json,correct_index,confidence,explanation,answer_source,voted_now,raw_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (q['fingerprint'], q['source'], q['message_id'], q['question'],
                       json.dumps(q['options'], ensure_ascii=False), q['correct_index'],
                       q['confidence'], q.get('explanation', ''), q.get('answer_source', ''), int(bool(q.get('voted_now'))), json.dumps(q, ensure_ascii=False), now()))

    def quizzes(self, source=None):
        with self.c() as x:
            if source:
                rows = x.execute('SELECT * FROM quizzes WHERE source=? ORDER BY id', (source,)).fetchall()
            else:
                rows = x.execute('SELECT * FROM quizzes ORDER BY id').fetchall()
            return [dict(r) for r in rows]

    def state(self, source):
        with self.c() as x:
            r = x.execute('SELECT * FROM scan_state WHERE source=?', (source,)).fetchone()
            return dict(r) if r else {'source': source, 'last_message_id': 0, 'checked': 0, 'found': 0}

    def save_state(self, source, last_message_id=None, checked=None, found=None):
        old = self.state(source)
        with self.c() as x:
            x.execute('''INSERT INTO scan_state(source,last_message_id,checked,found,updated_at)
                         VALUES(?,?,?,?,?)
                         ON CONFLICT(source) DO UPDATE SET
                           last_message_id=excluded.last_message_id,
                           checked=excluded.checked,
                           found=excluded.found,
                           updated_at=excluded.updated_at''',
                      (source,
                       old['last_message_id'] if last_message_id is None else int(last_message_id),
                       old['checked'] if checked is None else int(checked),
                       old['found'] if found is None else int(found),
                       now()))

    def log(self, level, message):
        with self.c() as x:
            x.execute('INSERT INTO logs(level,message,created_at) VALUES(?,?,?)', (level, str(message), now()))

    def logs(self):
        with self.c() as x:
            return '\n'.join(f"[{r[0]}] {r[1]}: {r[2]}" for r in x.execute('SELECT created_at,level,message FROM logs ORDER BY id DESC LIMIT 1000'))

    def hb(self, status, detail=''):
        with self.c() as x:
            x.execute('''INSERT INTO heartbeat(id,status,detail,updated_at) VALUES(1,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at''',
                      (status, str(detail), now()))

    def heartbeat(self):
        with self.c() as x:
            r = x.execute('SELECT * FROM heartbeat').fetchone()
            return dict(r) if r else None

    def count(self, table):
        allowed = {'quizzes', 'fingerprints', 'orders', 'sources'}
        if table not in allowed:
            raise ValueError('invalid table')
        with self.c() as x:
            return x.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
