"""QuizBot link -> Word workflow (userbot acts like a normal user inside @QuizBot).

Flow, exactly as the bot behaves in Telegram:
  1. /start <payload>                      -> "Get ready for the quiz ..."  [I am ready!]
  2. press "I am ready!"                   -> questions arrive as native quiz polls
                                              (an image question = image message, then its poll)
  3. every poll is answered so the quiz advances; Telegram then reveals the correct option
  4. "... was paused because you stopped answering"  [Resume Quiz] [Stop Quiz]
                                           -> press "Resume Quiz" (NEVER "Stop Quiz")
  5. "... has finished!"  [Try again] ...   -> finished: build ONE Word file and send it
                                              to the chat the link came from.

The correct option is always taken from Telegram's poll result, never guessed.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import time
from pathlib import Path

from telethon import errors

from userbot.scanner import (
    clean,
    fingerprint,
    image_suffix,
    poll_from_message,
    telegram_correct_index,
)
from utils.exporter import export
from utils.peers import resolve_peer
from utils.rate_limiter import GLOBAL_RATE_LIMITER, HOOKS, Hooks, StopRequested, interruptible_sleep

LINK_RE = re.compile(
    r'(?:https?://)?(?:t(?:elegram)?\.me/quizbot\?start=|tg://resolve\?domain=quizbot&start=)([A-Za-z0-9_-]+)',
    re.I,
)
CANCEL_WORDS = {'/cancel', 'cancel', 'bekor', 'bekor qilish', 'stop', 'to\'xtat'}

READY_LABELS = ('i am ready', "i'm ready")      # NOT 'start quiz': 'Start quiz in group' must never be pressed
RESUME_LABELS = ('resume quiz',)
FINISH_BUTTONS = ('try again',)
FINISH_TEXT = re.compile(r"(has finished!|you answered \d+ questions|quiz is over|test yakunlandi)", re.I)
TITLE_RE = re.compile(r"(?:get ready for the quiz|the quiz)\s*'(.+?)'", re.I | re.S)
COUNTER_RE = re.compile(r'^\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]\s*')

POLL_INTERVAL = 1.5          # seconds between looks at the QuizBot chat
NUDGE_AFTER = 60             # no news for this long -> re-check buttons (ready/resume)
GIVE_UP_EMPTY = 150          # nothing collected and no news for this long -> fail
FINISH_QUIET = 180           # collected something, no end marker, no news -> finish anyway
MAX_SECONDS = 3 * 60 * 60

_BOT_TIMEOUT = getattr(errors, 'BotResponseTimeoutError', None)


def _poll(msg):
    p = poll_from_message(msg)
    if p is None or not bool(getattr(p, 'quiz', False)):
        return None
    answers = list(getattr(p, 'answers', None) or [])
    question = clean(getattr(p, 'question', None))
    options = [clean(getattr(a, 'text', None)) for a in answers]
    if not question or len(options) < 2:
        return None
    return question, options, p, answers


def _is_image(msg) -> bool:
    if getattr(msg, 'photo', None) is not None:
        return True
    doc = getattr(msg, 'document', None)
    return bool(doc is not None and str(getattr(doc, 'mime_type', '') or '').lower().startswith('image/'))


def _find_button(msg, labels):
    """(row, col, label) of the first button whose label matches; 'stop' buttons never match."""
    for ri, row in enumerate(getattr(msg, 'buttons', None) or []):
        for ci, button in enumerate(row):
            label = clean(getattr(button, 'text', '') or '').strip().lower()
            if not label or label.startswith('stop'):
                continue
            if any(label == item or label.startswith(item) for item in labels):
                return ri, ci, label
    return None


def _strip_counter(question: str):
    """QuizBot prefixes questions with "[22/40] ": drop it, remember the total."""
    m = COUNTER_RE.match(question)
    if not m:
        return question, 0, 0
    return question[m.end():].strip(), int(m.group(1)), int(m.group(2))


def _title_from(raw: str) -> str:
    m = TITLE_RE.search(raw or '')
    if not m:
        return ''
    title = clean(m.group(1))
    title = re.split(r'[➤➔\n]', title)[0]
    title = re.sub(r'[^\w\s\-\.\,\(\)\'’‘ʻ]+', ' ', title, flags=re.U)
    return re.sub(r'\s+', ' ', title).strip()[:60]


class QuizBotWord:
    def __init__(self, db, output_dir='data/quizbot_word'):
        self.db = db
        self.output = Path(output_dir)
        self.output.mkdir(parents=True, exist_ok=True)
        self.active_users = set()
        self._cancel = set()
        self._bot_lock = asyncio.Lock()     # one QuizBot dialog -> one quiz at a time

    # ----------------------------------------------------------------- entry
    async def handle_link(self, client, event):
        if not event.is_private or getattr(event, 'out', False):
            return False
        uid = int(event.sender_id)
        raw = (event.raw_text or '').strip()
        if uid in self.active_users and raw.lower() in CANCEL_WORDS:
            self._cancel.add(uid)
            await event.reply('⛔ Bekor qilinmoqda...')
            return True
        match = LINK_RE.search(raw)
        if not match:
            return False
        if uid in self.active_users:
            await event.reply('⏳ Sizning QuizBot testingiz allaqachon ishlayapti. Avvalgisini tugating (bekor qilish: BEKOR).')
            return True
        self.active_users.add(uid)
        asyncio.create_task(self._run(client, event, uid, match.group(1)))
        return True

    async def _run(self, client, event, uid, payload):
        try:
            if self._bot_lock.locked():
                await self._reply(event, '⏳ QuizBot boshqa test bilan band. Navbatga qo‘ydim, avvalgisi tugagach boshlayman.')
            async with self._bot_lock:
                await self._run_locked(client, event, uid, payload)
        finally:
            self.active_users.discard(uid)
            self._cancel.discard(uid)
            HOOKS.set(None)

    async def _reply(self, event, text):
        try:
            await event.reply(text)
        except Exception:
            pass

    async def _rl(self, fn, key='global', retries=3):
        return await GLOBAL_RATE_LIMITER.call(fn, key=key, retries=retries)

    async def _click(self, client, msg, pos, label):
        ri, ci, _ = pos
        try:
            await self._rl(lambda: msg.click(ri, ci), key='click', retries=2)
            self.db.log('INFO', f'QuizBot: "{label}" bosildi (msg {msg.id})')
            return True
        except StopRequested:
            raise
        except Exception as exc:
            if _BOT_TIMEOUT is not None and isinstance(exc, _BOT_TIMEOUT):
                # The bot received the click but did not answer the callback in time: normal.
                self.db.log('INFO', f'QuizBot: "{label}" bosildi (msg {msg.id}, callback javobi kutilmadi)')
                return True
            self.db.log('WARN', f'QuizBot click "{label}" msg={msg.id}: {type(exc).__name__}: {exc}')
            return False

    # ------------------------------------------------------------------ main
    async def _run_locked(self, client, event, uid, payload):
        last_notice = [0.0]

        def notify(text):
            if time.monotonic() - last_notice[0] > 20:
                last_notice[0] = time.monotonic()
                asyncio.ensure_future(self._reply(event, text))

        HOOKS.set(Hooks(
            stop=lambda: uid in self._cancel,
            on_wait=lambda s, k: (self.db.log('WARN', f'⏳ QuizBot: Telegram limiti {s}s ({k})'),
                                  notify(f'⏳ Telegram limiti: {s} soniya kutaman, keyin o‘zi davom etadi.')),
            on_resume=lambda: notify('▶️ Limit tugadi, test davom etmoqda.'),
        ))

        out_dir = Path(tempfile.mkdtemp(prefix='quizbot_docx_'))
        rows = []
        try:
            await self._reply(event, '🔗 QuizBot testiga ulanmoqdaman. Shu test uchun alohida Word tayyorlayman.')
            entity = await resolve_peer(client, 'QuizBot')
            before = await self._rl(lambda: client.get_messages(entity, limit=1))
            last_id = int(before[0].id) if before else 0
            await self._rl(lambda: client.send_message(entity, '/start ' + payload))
            self.db.log('INFO', f'QuizBot START uid={uid} payload={payload}')

            seen_ids, clicked, seen_fp = set(), {}, {}
            prev_image = ''           # image sitting DIRECTLY above the next poll
            title, total = '', 0
            finished = False
            started = time.monotonic()
            last_activity = started
            last_nudge = 0.0
            first_id = last_id        # never touch messages from older sessions

            while time.monotonic() - started < MAX_SECONDS and not finished:
                msgs = await self._rl(lambda: client.get_messages(entity, limit=50, min_id=last_id, reverse=True))
                fresh = [m for m in msgs if int(m.id) > last_id and int(m.id) not in seen_ids]
                for msg in fresh:
                    mid = int(msg.id)
                    seen_ids.add(mid)
                    last_id = max(last_id, mid)
                    if getattr(msg, 'out', False):
                        continue
                    last_activity = time.monotonic()
                    raw = getattr(msg, 'message', '') or ''

                    if _is_image(msg):
                        dest = self.output / f'u{uid}_img_{mid}{image_suffix(msg)}'
                        try:
                            got = await self._rl(lambda: client.download_media(msg, file=str(dest)), retries=3)
                            prev_image = str(got) if got else ''
                        except StopRequested:
                            raise
                        except Exception as exc:
                            prev_image = ''
                            self.db.log('WARN', f'IMAGE LOST QuizBot msg={mid}: {type(exc).__name__}: {exc}')
                        continue

                    data = _poll(msg)
                    if data:
                        q_raw, options, poll, answers = data
                        question, number, n_total = _strip_counter(q_raw)
                        total = max(total, n_total)
                        image, prev_image = prev_image, ''
                        try:
                            correct, explanation, _voted = await telegram_correct_index(client, entity, msg, poll, answers)
                        except StopRequested:
                            raise
                        except Exception as exc:
                            correct, explanation = None, ''
                            self.db.log('WARN', f'QuizBot poll result unavailable msg={mid}: {type(exc).__name__}: {exc}')
                        fp = fingerprint(question, options)
                        if fp in seen_fp:                      # same question re-sent after Resume
                            row = rows[seen_fp[fp]]
                            if row['correct_index'] < 0 and correct is not None:
                                row['correct_index'] = int(correct)
                                row['explanation'] = clean(explanation or '')
                            if not row['image_path'] and image:
                                row['image_path'] = image
                            continue
                        seen_fp[fp] = len(rows)
                        rows.append({
                            'question': question, 'options': options,
                            'correct_index': int(correct) if correct is not None else -1,
                            'explanation': clean(explanation or ''),
                            'image_path': image,
                            'source_message_id': mid,
                        })
                        if len(rows) == 1 or len(rows) % 10 == 0:
                            await self._reply(event, f'📥 QuizBot: {len(rows)}' + (f'/{total}' if total else '') + ' savol qabul qilindi.')
                        continue

                    # Any other message breaks "image directly above the poll".
                    prev_image = ''
                    if not title:
                        title = _title_from(raw)
                    if _find_button(msg, FINISH_BUTTONS) or FINISH_TEXT.search(raw):
                        finished = True      # "Try again" appeared: the quiz is over, press nothing
                        continue
                    pos = _find_button(msg, READY_LABELS)
                    if pos and mid not in clicked:
                        clicked[mid] = time.monotonic()
                        await self._click(client, msg, pos, 'I am ready!')
                        continue
                    pos = _find_button(msg, RESUME_LABELS)
                    if pos and mid not in clicked:
                        clicked[mid] = time.monotonic()
                        await self._click(client, msg, pos, 'Resume Quiz')
                        continue

                if finished:
                    break

                idle = time.monotonic() - last_activity
                if not rows and idle > GIVE_UP_EMPTY:
                    break
                if rows and idle > FINISH_QUIET:
                    self.db.log('WARN', 'QuizBot: tugash belgisi (Try again) ko‘rinmadi, yig‘ilganini yuboraman')
                    break
                if idle > NUDGE_AFTER and time.monotonic() - last_nudge > 20:
                    last_nudge = time.monotonic()
                    await self._nudge(client, entity, clicked, first_id)
                await interruptible_sleep(POLL_INTERVAL)

            if not rows:
                await self._reply(event, '❌ QuizBot’dan native quiz savollari olinmadi. Link yaroqliligini tekshiring.')
                return

            files = await asyncio.to_thread(export, rows, max(1, len(rows)), title or 'quiz_test', out_dir)
            unknown = sum(1 for r in rows if r['correct_index'] < 0)
            caption = f'✅ QuizBot testi yakunlandi: {len(rows)}' + (f'/{total}' if total else '') + ' savol.'
            if total and len(rows) < total:
                caption += f'\n⚠️ {total - len(rows)} ta savol olinmadi.'
            if unknown:
                caption += f'\n⚠️ {unknown} ta savolda to‘g‘ri javob Telegram natijasida ko‘rinmadi (belgilanmagan).'
            for path in files:
                await self._rl(lambda p=path: client.send_file(event.chat_id, str(p), caption=caption), key='send', retries=3)
            self.db.log('INFO', f'QuizBot DOCX sent uid={uid}; payload={payload}; questions={len(rows)}/{total}; unknown_answers={unknown}')
        except StopRequested:
            self.db.log('INFO', f'QuizBot bekor qilindi uid={uid}')
            await self._reply(event, '⛔ QuizBot jarayoni bekor qilindi.')
        except Exception as exc:
            self.db.log('ERROR', f'QuizBot workflow uid={uid}: {type(exc).__name__}: {exc}')
            await self._reply(event, f'❌ QuizBot jarayonida xatolik: {type(exc).__name__}. Loglarni tekshiring.')
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
            for row in rows:
                if row.get('image_path'):
                    Path(row['image_path']).unlink(missing_ok=True)

    async def _nudge(self, client, entity, clicked, first_id):
        """Nothing new for a while: re-read the latest messages (edits included) and press a
        waiting "I am ready!" / "Resume Quiz" again (at most once per minute per message)."""
        recent = await self._rl(lambda: client.get_messages(entity, limit=10))
        for msg in recent:
            if getattr(msg, 'out', False) or int(msg.id) <= first_id:
                continue
            for labels, name in ((READY_LABELS, 'I am ready!'), (RESUME_LABELS, 'Resume Quiz')):
                pos = _find_button(msg, labels)
                if pos and time.monotonic() - clicked.get(int(msg.id), 0) > 60:
                    clicked[int(msg.id)] = time.monotonic()
                    await self._click(client, msg, pos, name + ' (qayta)')
                    return
