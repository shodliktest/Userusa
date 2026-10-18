"""Persistent state in a private Telegram "storage" channel.

What is stored (one zip document per snapshot, newest N kept):
  * userbot.db        - sources, fingerprints, quizzes, scan checkpoints, intake
  * intake/           - images of the user's current private-chat collections
  * scanner_images/   - images paired with scanned quizzes (skipped if > max size)

On start-up, if the local database holds no data (fresh container / redeploy),
the newest snapshot is downloaded and restored before the bot starts working.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from utils.peers import resolve_peer

PREFIX = 'userbot_state_'
FOLDERS = ('intake', 'scanner_images')


class TelegramBackup:
    def __init__(self, db, channel='', base='data', min_interval=120, keep=3, max_images_mb=150):
        self.db = db
        self.channel = str(channel or '').strip()
        self.base = Path(base)
        self.min_interval = float(min_interval)
        self.keep = max(1, int(keep))
        self.max_images = int(max_images_mb) * 1024 * 1024
        self.last_ok = ''
        self.last_error = ''
        self._want = False
        self._last_sig = None
        self._last_upload = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.channel)

    def request(self):
        """Ask for a snapshot soon (called after important events)."""
        self._want = True

    # ------------------------------------------------------------------ helpers
    def _signature(self):
        sig = []
        try:
            st = self.db.p.stat()
            sig.append((st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append(None)
        for folder in FOLDERS:
            n = 0
            newest = 0
            for root, _dirs, files in os.walk(self.base / folder):
                for f in files:
                    try:
                        newest = max(newest, os.stat(os.path.join(root, f)).st_mtime_ns)
                        n += 1
                    except OSError:
                        pass
            sig.append((n, newest))
        return tuple(sig)

    def _build_zip(self, dest: Path):
        tmp_db = dest.with_suffix('.db')
        self.db.snapshot(tmp_db)
        skipped = []
        try:
            with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(tmp_db, 'userbot.db')
                for folder in FOLDERS:
                    root = self.base / folder
                    if not root.is_dir():
                        continue
                    files = [p for p in root.rglob('*') if p.is_file()]
                    size = 0
                    for p in files:
                        try:
                            size += p.stat().st_size
                        except OSError:
                            pass
                    if folder == 'scanner_images' and size > self.max_images:
                        skipped.append(folder)
                        continue
                    for p in files:
                        try:
                            z.write(p, f'{folder}/{p.relative_to(root).as_posix()}')
                        except OSError:
                            pass
        finally:
            tmp_db.unlink(missing_ok=True)
        return skipped

    def _apply_zip(self, zpath: Path):
        self.db.p.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='tg_restore_', dir=str(self.db.p.parent)))
        try:
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                if 'userbot.db' not in names:
                    raise ValueError('zaxira ichida userbot.db yo‘q')
                dbtmp = stage / 'userbot.db'
                with z.open('userbot.db') as src, open(dbtmp, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                con = sqlite3.connect(dbtmp)
                try:
                    verdict = con.execute('PRAGMA integrity_check').fetchone()[0]
                finally:
                    con.close()
                if verdict != 'ok':
                    raise ValueError(f'zaxira bazasi buzilgan: {verdict}')
                for name in names:
                    if name == 'userbot.db' or name.endswith('/'):
                        continue
                    p = Path(name)
                    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in FOLDERS:
                        continue
                    target = self.base.joinpath(*p.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            for suffix in ('-wal', '-shm', '-journal'):
                Path(str(self.db.p) + suffix).unlink(missing_ok=True)
            os.replace(dbtmp, self.db.p)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _is_state(m) -> bool:
        try:
            return bool(m.file and (m.file.name or '').startswith(PREFIX))
        except Exception:
            return False

    # ------------------------------------------------------------------ restore
    async def restore_if_needed(self, client) -> bool:
        if not self.enabled:
            return False
        if await asyncio.to_thread(self.db.has_state):
            return False
        entity = await resolve_peer(client, self.channel)
        found = None
        async for m in client.iter_messages(entity, limit=100):
            if self._is_state(m):
                found = m
                break
        if found is None:
            self.db.log('INFO', 'Storage kanalida zaxira topilmadi (yangi boshlanish)')
            return False
        tmpdir = Path(tempfile.mkdtemp(prefix='tg_dl_'))
        try:
            path = await client.download_media(found, file=str(tmpdir / 'state.zip'))
            if not path:
                raise RuntimeError('zaxirani yuklab bo‘lmadi')
            await asyncio.to_thread(self._apply_zip, Path(path))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        self.db.init()
        self._last_sig = await asyncio.to_thread(self._signature)
        self._last_upload = time.monotonic()
        self.last_ok = 'tiklandi'
        return True

    # ------------------------------------------------------------------- backup
    async def backup_now(self, client):
        entity = await resolve_peer(client, self.channel)
        tmpdir = Path(tempfile.mkdtemp(prefix='tg_state_'))
        try:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            zpath = tmpdir / f'{PREFIX}{stamp}.zip'
            skipped = await asyncio.to_thread(self._build_zip, zpath)
            caption = f'#userbot_state {stamp}'
            if skipped:
                caption += ' (rasm papkasi katta: ' + ', '.join(skipped) + ' kiritilmadi)'
            await client.send_file(entity, str(zpath), caption=caption, force_document=True)
            msgs = await client.get_messages(entity, limit=60)
            old = [m for m in msgs if self._is_state(m)][self.keep:]
            if old:
                await client.delete_messages(entity, [m.id for m in old])
            self.last_ok = stamp
            self.last_error = ''
            if skipped:
                self.db.log('WARN', f'Zaxira: {", ".join(skipped)} hajmi chegaradan katta, kiritilmadi')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def run(self, client):
        self.db.log('INFO', 'Telegram storage zaxirasi yoqilgan')
        while True:
            try:
                await asyncio.sleep(15)
                if not await asyncio.to_thread(self.db.has_state):
                    continue
                sig = await asyncio.to_thread(self._signature)
                if sig == self._last_sig:
                    continue
                gap = time.monotonic() - self._last_upload
                if gap < (20 if self._want else self.min_interval):
                    continue
                await self.backup_now(client)
                self._want = False
                self._last_upload = time.monotonic()
                self.db.log('INFO', 'Zaxira Telegram storage kanaliga yuklandi')
                # Signature is taken AFTER the log line so the log itself does not
                # trigger another upload.
                self._last_sig = await asyncio.to_thread(self._signature)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
                self._last_upload = time.monotonic()
                try:
                    self.db.log('ERROR', f'Zaxira xatosi: {self.last_error}')
                except Exception:
                    pass
