import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, p=Path('data/userbot.db')):
        p.parent.mkdir(parents=True, exist_ok=True)
        self.p = p
        self.init()

    @contextmanager
    def c(self):
        """Connection that commits on success and ALWAYS closes (no leaked handles)."""
        x = sqlite3.connect(self.p, timeout=30)
        x.row_factory = sqlite3.Row
        try:
            yield x
            x.commit()
        except BaseException:
            x.rollback()
            raise
        finally:
            x.close()

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
                file_publish_enabled INTEGER DEFAULT 1,
                scan_mode TEXT DEFAULT 'target',
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
                image_path TEXT DEFAULT '',
                raw_json TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,user_id TEXT,data_json TEXT,status TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,level TEXT,message TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),status TEXT,detail TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS scan_state(source TEXT PRIMARY KEY,last_message_id INTEGER DEFAULT 0,checked INTEGER DEFAULT 0,found INTEGER DEFAULT 0,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS intake_sessions(
                user_id INTEGER PRIMARY KEY,
                pending_image_path TEXT DEFAULT '',
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS intake_pending_images(
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS intake_items(
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                message_id INTEGER,
                question TEXT,
                options_json TEXT,
                correct_index INTEGER,
                explanation TEXT DEFAULT '',
                answer_source TEXT DEFAULT 'telegram_poll_results',
                voted_now INTEGER DEFAULT 0,
                image_path TEXT DEFAULT '',
                created_at TEXT,
                UNIQUE(user_id, fingerprint)
            );
            ''')
            # Safe migrations for databases created by earlier versions.
            cols = {r[1] for r in x.execute('PRAGMA table_info(sources)')}
            if 'publish_enabled' not in cols:
                x.execute('ALTER TABLE sources ADD COLUMN publish_enabled INTEGER DEFAULT 0')
            if 'file_publish_enabled' not in cols:
                x.execute('ALTER TABLE sources ADD COLUMN file_publish_enabled INTEGER DEFAULT 1')
            if 'scan_mode' not in cols:
                x.execute("ALTER TABLE sources ADD COLUMN scan_mode TEXT DEFAULT 'target'")
            if 'enabled' not in cols:
                x.execute('ALTER TABLE sources ADD COLUMN enabled INTEGER DEFAULT 1')
            if 'answer_source' not in {r[1] for r in x.execute('PRAGMA table_info(quizzes)')}:
                x.execute("ALTER TABLE quizzes ADD COLUMN answer_source TEXT DEFAULT ''")
            if 'voted_now' not in {r[1] for r in x.execute('PRAGMA table_info(quizzes)')}:
                x.execute("ALTER TABLE quizzes ADD COLUMN voted_now INTEGER DEFAULT 0")
            if 'image_path' not in {r[1] for r in x.execute('PRAGMA table_info(quizzes)')}:
                x.execute("ALTER TABLE quizzes ADD COLUMN image_path TEXT DEFAULT ''")

    def sources(self):
        with self.c() as x:
            return [dict(r) for r in x.execute('SELECT * FROM sources ORDER BY id DESC')]

    def add_source(self, s, n=100, pf=20, out='', publish_enabled=0, file_publish_enabled=1, scan_mode='target'):
        s = str(s).strip()
        with self.c() as x:
            x.execute('''INSERT INTO sources(source,target_count,per_file,output_chat,publish_enabled,file_publish_enabled,scan_mode,created_at)
                         VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(source) DO UPDATE SET
                           target_count=excluded.target_count,
                           per_file=excluded.per_file,
                           output_chat=excluded.output_chat,
                           publish_enabled=excluded.publish_enabled,
                           file_publish_enabled=excluded.file_publish_enabled,
                           scan_mode=excluded.scan_mode,
                           enabled=1''',
                      (s, int(n), int(pf), str(out).strip(), int(bool(publish_enabled)), int(bool(file_publish_enabled)), str(scan_mode or 'target'), now()))

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
                (fingerprint,source,message_id,question,options_json,correct_index,confidence,explanation,answer_source,voted_now,image_path,raw_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (q['fingerprint'], q['source'], q['message_id'], q['question'],
                       json.dumps(q['options'], ensure_ascii=False), q['correct_index'],
                       q['confidence'], q.get('explanation', ''), q.get('answer_source', ''), int(bool(q.get('voted_now'))), q.get('image_path', '') or '', json.dumps(q, ensure_ascii=False), now()))

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
        stamp = now()
        with self.c() as x:
            x.execute('INSERT INTO logs(level,message,created_at) VALUES(?,?,?)', (level, str(message), stamp))
        # Console (terminal / Streamlit Cloud "Manage app" logs). Disable: LOG_TO_CONSOLE=0
        if os.getenv('LOG_TO_CONSOLE', '1') != '0':
            try:
                print(f'[{stamp}] {level}: {message}', flush=True)
            except Exception:
                pass

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


    # --- Private user intake: photo -> quiz pairs -------------------------
    def intake_set_pending_image(self, user_id, path, message_id=0):
        """Backward-compatible single pending image API; now backed by FIFO queue."""
        self.intake_add_pending_image(user_id, message_id, path)

    def intake_add_pending_image(self, user_id, message_id, path):
        with self.c() as x:
            x.execute(
                "INSERT INTO intake_pending_images(user_id,message_id,image_path,created_at) VALUES(?,?,?,?)",
                (int(user_id), int(message_id or 0), str(path), now()),
            )
            x.execute(
                """INSERT INTO intake_sessions(user_id,pending_image_path,updated_at)
                   VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     pending_image_path=excluded.pending_image_path,
                     updated_at=excluded.updated_at""",
                (int(user_id), str(path), now()),
            )

    def intake_take_pending_image(self, user_id):
        """Pop the oldest pending image (FIFO) and keep legacy API semantics."""
        with self.c() as x:
            r = x.execute(
                'SELECT id,image_path FROM intake_pending_images WHERE user_id=? ORDER BY id LIMIT 1',
                (int(user_id),),
            ).fetchone()
            if not r:
                # Legacy row may exist from an older version.
                legacy = x.execute(
                    'SELECT pending_image_path FROM intake_sessions WHERE user_id=?',
                    (int(user_id),),
                ).fetchone()
                path = str(legacy[0] or '') if legacy else ''
                if legacy:
                    x.execute('UPDATE intake_sessions SET pending_image_path="",updated_at=? WHERE user_id=?', (now(), int(user_id)))
                return path

            path = str(r['image_path'] or '')
            x.execute('DELETE FROM intake_pending_images WHERE id=?', (int(r['id']),))
            nxt = x.execute(
                'SELECT image_path FROM intake_pending_images WHERE user_id=? ORDER BY id LIMIT 1',
                (int(user_id),),
            ).fetchone()
            x.execute(
                'UPDATE intake_sessions SET pending_image_path=?,updated_at=? WHERE user_id=?',
                (str(nxt[0] or '') if nxt else '', now(), int(user_id)),
            )
            return path

    def intake_pending_count(self, user_id):
        with self.c() as x:
            return int(x.execute('SELECT count(*) FROM intake_pending_images WHERE user_id=?', (int(user_id),)).fetchone()[0])

    def intake_take_pending_image_for_message(self, user_id, message_id):
        """Pop a queued image only if its Telegram message_id matches exactly."""
        with self.c() as x:
            r = x.execute(
                'SELECT id,image_path FROM intake_pending_images WHERE user_id=? AND message_id=? ORDER BY id LIMIT 1',
                (int(user_id), int(message_id)),
            ).fetchone()
            if not r:
                return ''
            path = str(r['image_path'] or '')
            x.execute('DELETE FROM intake_pending_images WHERE id=?', (int(r['id']),))
            nxt = x.execute(
                'SELECT image_path FROM intake_pending_images WHERE user_id=? ORDER BY id LIMIT 1',
                (int(user_id),),
            ).fetchone()
            x.execute(
                'UPDATE intake_sessions SET pending_image_path=?,updated_at=? WHERE user_id=?',
                (str(nxt[0] or '') if nxt else '', now(), int(user_id)),
            )
            return path

    def intake_has_fingerprint(self, user_id, fingerprint):
        with self.c() as x:
            return x.execute('SELECT 1 FROM intake_items WHERE user_id=? AND fingerprint=?', (int(user_id), str(fingerprint))).fetchone() is not None

    def intake_add(self, user_id, q):
        with self.c() as x:
            x.execute("""INSERT OR IGNORE INTO intake_items
                (user_id,fingerprint,message_id,question,options_json,correct_index,explanation,answer_source,voted_now,image_path,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (int(user_id), q['fingerprint'], int(q['message_id']), q['question'],
                 json.dumps(q['options'], ensure_ascii=False), int(q['correct_index']),
                 q.get('explanation',''), q.get('answer_source','telegram_poll_results'),
                 int(bool(q.get('voted_now'))), q.get('image_path',''), now()))

    def intake_items(self, user_id):
        with self.c() as x:
            rows = x.execute('SELECT * FROM intake_items WHERE user_id=? ORDER BY id', (int(user_id),)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d['options'] = json.loads(d.get('options_json') or '[]')
                except Exception:
                    d['options'] = []
                out.append(d)
            return out

    def intake_stats(self, user_id):
        with self.c() as x:
            r = x.execute("""SELECT
                count(*) AS count,
                sum(CASE WHEN image_path IS NOT NULL AND image_path <> '' THEN 1 ELSE 0 END) AS with_image
                FROM intake_items WHERE user_id=?""", (int(user_id),)).fetchone()
            pending = x.execute('SELECT image_path FROM intake_pending_images WHERE user_id=? ORDER BY id LIMIT 1', (int(user_id),)).fetchone()
            pending_count = int(x.execute('SELECT count(*) FROM intake_pending_images WHERE user_id=?', (int(user_id),)).fetchone()[0])
            count = int(r['count'] or 0)
            with_image = int(r['with_image'] or 0)
            return {'count': count, 'with_image': with_image, 'without_image': count-with_image,
                    'pending_image': str(pending[0] or '') if pending else '',
                    'pending_count': pending_count}

    def intake_pending_paths(self, user_id):
        with self.c() as x:
            return [str(r[0] or '') for r in x.execute('SELECT image_path FROM intake_pending_images WHERE user_id=? ORDER BY id', (int(user_id),)).fetchall() if r[0]]

    def intake_claim(self, user_id):
        """Atomically take ALL collected items of a user and remove them from the DB.

        Once claimed, a batch can never leak into the next collection, even if the
        export/send step fails later (use intake_restore to put it back then).
        """
        with self.c() as x:
            x.execute('BEGIN IMMEDIATE')
            rows = x.execute('SELECT * FROM intake_items WHERE user_id=? ORDER BY id', (int(user_id),)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d['options'] = json.loads(d.get('options_json') or '[]')
                except Exception:
                    d['options'] = []
                out.append(d)
            x.execute('DELETE FROM intake_items WHERE user_id=?', (int(user_id),))
            return out

    def intake_restore(self, user_id, rows):
        for d in rows:
            self.intake_add(user_id, d)

    def intake_clear(self, user_id):
        with self.c() as x:
            x.execute('DELETE FROM intake_items WHERE user_id=?', (int(user_id),))
            x.execute('DELETE FROM intake_pending_images WHERE user_id=?', (int(user_id),))
            x.execute('DELETE FROM intake_sessions WHERE user_id=?', (int(user_id),))

    # --- Persistence helpers (Telegram storage channel) --------------------
    def has_state(self):
        """True if the DB holds any real data (used to decide on restore)."""
        with self.c() as x:
            for t in ('sources', 'fingerprints', 'quizzes', 'scan_state', 'intake_items', 'intake_pending_images'):
                if x.execute(f'SELECT 1 FROM {t} LIMIT 1').fetchone():
                    return True
        return False

    def snapshot(self, dest):
        """Consistent copy of the live database (sqlite online-backup API)."""
        src = sqlite3.connect(self.p, timeout=30)
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()

    def count(self, table):
        allowed = {'quizzes', 'fingerprints', 'orders', 'sources'}
        if table not in allowed:
            raise ValueError('invalid table')
        with self.c() as x:
            return x.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
