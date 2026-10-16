"""QuizBot link-to-DOCX workflow (best-effort Telegram client automation).

A separate per-request session is created for each incoming QuizBot deep link.
Correct options are requested from Telegram poll results, never guessed by AI.
"""
from __future__ import annotations
import asyncio, re, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from telethon import events
from telethon.tl.types import MessageMediaPoll
from docx import Document
from docx.shared import Cm, Pt
from userbot.scanner import poll_from_message, telegram_correct_index, clean

LINK_RE = re.compile(r'(?:https?://)?t\.me/QuizBot\?start=([A-Za-z0-9_-]+)', re.I)
END_RE = re.compile(r'(quiz (?:completed|finished|ended)|test (?:completed|finished|ended)|your result|result:|correct answers|you answered|quiz is over|test yakunlandi)', re.I)

def _poll(msg):
    p = poll_from_message(msg)
    if p is None or not bool(getattr(p, "quiz", False)):
        return None
    answers = list(getattr(p, "answers", None) or [])
    question = clean(getattr(p, "question", None))
    options = [clean(getattr(a, "text", None)) for a in answers]
    if not question or len(options) < 2:
        return None
    return question, options, p, answers


async def _click_progress_button(client, msg):
    """Click only obvious navigation controls, never arbitrary answer buttons."""
    buttons = getattr(msg, "buttons", None) or []
    allowed = ("start quiz", "start test", "begin quiz", "next question", "next", "continue", "start")
    for ri, row in enumerate(buttons):
        for ci, button in enumerate(row):
            label = clean(getattr(button, "text", "") or "").strip().lower()
            if label and any(label == item or label.startswith(item + " ") for item in allowed):
                try:
                    await msg.click(ri, ci)
                    return True
                except Exception:
                    try:
                        await msg.click(ci, ri)
                        return True
                    except Exception:
                        pass
    return False

def _safe_name(s):
    s = re.sub(r'[\\/:*?"<>|]+', " ", clean(s))
    return (s.strip()[:70] or "QuizBot_test")

class QuizBotWord:
    def __init__(self, db, output_dir="data/quizbot_word"):
        self.db = db
        self.output = Path(output_dir)
        self.output.mkdir(parents=True, exist_ok=True)
        self.active_users = set()
        self.active_bot_chat = False

    async def handle_link(self, client, event):
        if not event.is_private:
            return False
        match = LINK_RE.search(event.raw_text or "")
        if not match:
            return False
        uid = int(event.sender_id)
        if uid in self.active_users:
            await event.reply("⏳ Sizning QuizBot testingiz allaqachon ishlayapti. Avvalgisini tugating.")
            return True
        self.active_users.add(uid)
        asyncio.create_task(self._run(client, event, uid, match.group(1)))
        return True

    async def _run(self, client, event, uid, payload):
        self.active_bot_chat = True
        try:
            await event.reply("🔗 QuizBot testiga ulanmoqdaman. Shu test uchun alohida Word tayyorlayman.")
            entity = await client.get_entity("QuizBot")
            before = await client.get_messages(entity, limit=1)
            last_id = int(before[0].id) if before else 0
            # Deep-link equivalent: start the exact payload in the bot's private chat.
            await client.send_message(entity, "/start " + payload)
            await asyncio.sleep(1.5)
            rows = []
            seen = set()
            pending_image = ""
            started = time.monotonic()
            last_activity = started
            # Poll the QuizBot dialog. The quiz can advance after a vote, so
            # newly arriving poll messages are collected in order.
            while time.monotonic() - started < 3 * 60 * 60:
                msgs = await client.get_messages(entity, limit=30, min_id=last_id, reverse=True)
                if not msgs:
                    # Auto-finish only after a strong end marker and a quiet interval.
                    if rows and time.monotonic() - last_activity > 90:
                        break
                    await asyncio.sleep(2)
                    continue
                for msg in msgs:
                    if int(msg.id) <= last_id or int(msg.id) in seen:
                        continue
                    seen.add(int(msg.id))
                    last_id = max(last_id, int(msg.id))
                    last_activity = time.monotonic()
                    if msg.photo or (getattr(msg, "document", None) and str(getattr(msg.document, "mime_type", "")).startswith("image/")):
                        dest = self.output / f"u{uid}_img_{msg.id}"
                        try:
                            got = await client.download_media(msg, file=str(dest))
                            if got:
                                pending_image = str(got)
                        except Exception as exc:
                            self.db.log("WARN", f"QuizBot image download: {exc}")
                    # QuizBot often presents an inline Start/Next control between questions.
                    # Click only recognized navigation labels; never choose a quiz answer here.
                    await _click_progress_button(client, msg)
                    data = _poll(msg)
                    if data:
                        q, options, poll, answers = data
                        correct = None
                        explanation = ""
                        try:
                            correct, explanation, _voted = await telegram_correct_index(client, entity, msg, poll, answers)
                        except Exception as exc:
                            self.db.log("WARN", f"QuizBot poll result unavailable msg_id={msg.id}: {type(exc).__name__}: {exc}")
                        rows.append({
                            "question": q, "options": options,
                            "correct_index": int(correct) if correct is not None else -1,
                            "explanation": clean(explanation or ""),
                            "image_path": pending_image or "",
                            "source_message_id": int(msg.id),
                        })
                        pending_image = ""
                        await event.reply(f"📥 QuizBot savoli {len(rows)} qabul qilindi.")
                        continue
                    body = clean(getattr(msg, "message", "") or "")
                    if END_RE.search(body) and rows:
                        await asyncio.sleep(2)
                        break
                if rows and time.monotonic() - last_activity > 120:
                    break
                await asyncio.sleep(1.5)

            if not rows:
                await event.reply("❌ QuizBot’dan native quiz savollari olinmadi. Link yaroqliligini va test akkauntda ochilishini tekshiring.")
                return
            path = self._make_docx(rows, uid, payload)
            await client.send_file(
                event.chat_id, str(path),
                caption=f"✅ QuizBot testi yakunlandi. {len(rows)} ta savol Word faylga yig‘ildi.\n"
                        "To‘g‘ri javoblar Telegram natijasi ko‘ringan savollardagina belgilangan."
            )
            self.db.log("INFO", f"QuizBot DOCX sent uid={uid}; payload={payload}; questions={len(rows)}")
        except Exception as exc:
            self.db.log("ERROR", f"QuizBot workflow uid={uid}: {type(exc).__name__}: {exc}")
            try:
                await event.reply(f"❌ QuizBot jarayonida xatolik: {type(exc).__name__}. Loglarni tekshiring.")
            except Exception:
                pass
        finally:
            self.active_users.discard(uid)
            self.active_bot_chat = False

    def _make_docx(self, rows, uid, payload):
        doc = Document()
        sec = doc.sections[0]
        sec.top_margin = Cm(1.7); sec.bottom_margin = Cm(1.7)
        sec.left_margin = Cm(2); sec.right_margin = Cm(2)
        for n, row in enumerate(rows, 1):
            img = row.get("image_path", "")
            if img and Path(img).is_file():
                try:
                    p = doc.add_paragraph()
                    p.alignment = 1
                    p.add_run().add_picture(img, width=Cm(15))
                except Exception:
                    pass
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(f"{n}. {clean(row.get('question',''))}")
            r.bold = True
            for i, option in enumerate(row.get("options", [])[:26]):
                mark = "*" if i == row.get("correct_index", -1) else ""
                doc.add_paragraph(f"{mark}{chr(65+i)}) {clean(option)}")
            if row.get("explanation"):
                doc.add_paragraph("Izoh: " + clean(row["explanation"]))
            doc.add_paragraph()
        dest = self.output / f"{_safe_name(rows[0].get('question','QuizBot_test'))}_{uid}_{int(time.time())}.docx"
        doc.save(dest)
        return dest
