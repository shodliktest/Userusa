import asyncio
import threading

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config.settings import load_settings
from storage.database import Database
from ai.operator import Operator
from userbot.scanner import scan


class Worker:
    def __init__(self):
        self.s = load_settings()
        self.db = Database()
        self.loop = None
        self.client = None
        self.thread = None
        self.running = False
        self.scanning = False
        self.scan_future = None
        self.stop_event = threading.Event()
        self.stats = {'status': 'stopped', 'source': '', 'checked': 0, 'found': 0, 'skipped': 0, 'published': 0, 'error': ''}
        self.hist = {}
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self.run, name='telegram-userbot', daemon=True)
            self.thread.start()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.main())
        except Exception as exc:
            self.running = False
            self.db.hb('error', str(exc))
            self.db.log('ERROR', f'Worker: {exc}')
        finally:
            self.running = False

    async def main(self):
        if not self.s.session_string:
            self.db.hb('error', 'TELEGRAM_SESSION_STRING yo‘q')
            return
        self.client = TelegramClient(StringSession(self.s.session_string), self.s.api_id, self.s.api_hash)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            self.db.hb('error', 'Session authorized emas')
            return

        op = Operator()
        self.running = True
        self.db.hb('running', 'Telegram ulangan')
        self.db.log('INFO', 'UserBot connected')

        @self.client.on(events.NewMessage(incoming=True))
        async def incoming(e):
            if not e.is_private:
                return
            text = (e.raw_text or '').strip()
            if not text:
                return
            try:
                history = self.hist.setdefault(str(e.sender_id), [])
                answer = op.reply(history, text)
                history.extend([{'role': 'user', 'content': text}, {'role': 'assistant', 'content': answer}])
                del history[:-14]
                await e.reply(answer)
            except Exception as exc:
                self.db.log('ERROR', f'Operator: {exc}')

        await self.client.run_until_disconnected()

    def start_scan(self, rows=None):
        with self.lock:
            if not self.running or self.loop is None or self.client is None:
                self.stats.update(status='error', error='UserBot hali Telegramga ulanmagan')
                return False
            if self.scanning:
                return False
            rows = rows if rows is not None else self.db.sources()
            rows = [r for r in rows if int(r.get('enabled', 1))]
            if not rows:
                self.stats.update(status='error', error='Scanner uchun manba saqlanmagan')
                return False
            self.stop_event.clear()
            self.scanning = True
            self.stats = {'status': 'starting', 'source': '', 'checked': 0, 'found': 0, 'skipped': 0, 'published': 0, 'error': ''}
            self.db.log('INFO', f'Scanner START: {len(rows)} source')
            self.scan_future = asyncio.run_coroutine_threadsafe(self._scan_all(rows), self.loop)
            return True

    async def _scan_all(self, rows):
        try:
            for row in rows:
                if self.stop_event.is_set():
                    break
                source = str(row['source']).strip()
                try:
                    self.db.log('INFO', f"Scan START: {source}; target={row['target_count']}")
                    n = await scan(
                        self.client, self.db, source, int(row['target_count']),
                        self.stop_event, self.s, self.stats,
                        output_chat=str(row.get('output_chat') or '').strip(),
                        publish_enabled=bool(row.get('publish_enabled', 0)),
                    )
                    self.db.log('INFO', f'Scan DONE: {source}; found={n}')
                except Exception as exc:
                    self.db.log('ERROR', f'Scan {source}: {exc}')
                    self.stats['error'] = str(exc)
                    self.stats['status'] = 'error'
                    # Continue to the next configured source unless user pressed stop.
            if self.stop_event.is_set():
                self.stats['status'] = 'stopped'
            elif self.stats.get('status') != 'error':
                self.stats['status'] = 'completed'
        finally:
            self.scanning = False
            self.scan_future = None

    def stop_scan(self):
        with self.lock:
            if not self.scanning:
                return False
            self.stop_event.set()
            self.stats['status'] = 'stopping'
            self.db.log('INFO', 'Scanner STOP requested')
            return True


W = None


def get_worker():
    global W
    if W is None:
        W = Worker()
    return W


def ensure_worker_started():
    get_worker().start()
    return True


def worker_is_alive():
    w = get_worker()
    return bool(w.thread and w.thread.is_alive() and w.running)
