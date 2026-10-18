"""Production private-chat intake for Telegram quiz/viktorina messages.

Accepted patterns:
    photo -> quiz
    photo -> forwarded quiz
    quiz
    forwarded quiz
    many photo/quiz pairs

The poll answer is ALWAYS obtained from Telegram's poll results. AI is not
used for answer extraction. True forwarded polls get a second addressing path:
the private-chat copy first, then the original peer/message from fwd_from.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path
from typing import Any

from telethon import errors

from userbot.scanner import (
    clean,
    fingerprint,
    forwarded_origin,
    is_poll_message,
    image_suffix,
    poll_from_message,
    telegram_correct_index,
)

COMMAND_INFO = "INFO"
COMMAND_FINISH = "YAKUNLASH"


def _quiz_data(msg: Any):
    poll = poll_from_message(msg)
    if poll is None or not bool(getattr(poll, "quiz", False)):
        return None
    question = clean(getattr(poll, "question", None))
    answers = list(getattr(poll, "answers", None) or [])
    options = [clean(getattr(a, "text", None)) for a in answers]
    if not question or len(options) < 2 or any(not x for x in options):
        return None
    return question, options, poll, answers


def _safe_name(value: str) -> str:
    value = clean(value)
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    return (value[:70].strip() or "quizlar")


def _is_image_message(msg: Any) -> bool:
    if getattr(msg, "photo", None) is not None:
        return True
    document = getattr(msg, "document", None)
    if document is not None:
        mime = str(getattr(document, "mime_type", "") or "").lower()
        if mime.startswith("image/"):
            return True
    media = getattr(msg, "media", None)
    name = media.__class__.__name__.lower() if media is not None else ""
    return "photo" in name


class IntakeManager:
    def __init__(self, db, base_dir="data/intake", on_change=None):
        self.db = db
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self._on_change = on_change
        self._locks = {}

    def _changed(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def _lock(self, uid: int) -> asyncio.Lock:
        lock = self._locks.get(uid)
        if lock is None:
            lock = self._locks[uid] = asyncio.Lock()
        return lock

    def _image_path(self, uid: int, msg) -> Path:
        return self._user_dir(uid) / f"img_{int(msg.id)}{image_suffix(msg)}"

    async def _download_image(self, client, msg, path: Path) -> str:
        if path.is_file() and path.stat().st_size > 0:
            return str(path)
        got = await client.download_media(msg, file=str(path))
        return str(got) if got else ""

    async def _paired_image(self, client, event, uid: int, quiz_msg) -> str:
        """Image that sits IMMEDIATELY above this quiz in the chat.

        Messages the bot itself sent ("Rasm qabul qilindi" replies) are skipped,
        so  image(12) -> [bot reply] -> quiz(13)  still pairs 12 with 13.
        No FIFO guessing: a quiz without an image right above it stays image-less.
        """
        recent = await client.get_messages(event.chat_id, limit=8, max_id=int(quiz_msg.id))
        prev = next((m for m in recent if not getattr(m, "out", False)), None)
        if prev is None or not _is_image_message(prev):
            return ""
        pending = self.db.intake_take_pending_image_for_message(uid, int(prev.id))
        if pending and Path(pending).is_file():
            return pending
        return await self._download_image(client, prev, self._image_path(uid, prev))

    def _drop_pending(self, uid: int):
        for pending in self.db.intake_pending_paths(uid):
            Path(pending).unlink(missing_ok=True)
        self.db.intake_clear(uid)

    def _user_dir(self, user_id: int | str) -> Path:
        p = self.base / str(user_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def _refresh_quiz(self, client, event, msg):
        """Fetch the exact private message repeatedly, but only when it looks poll-like."""
        data = _quiz_data(msg)
        if data is not None:
            return msg, data

        pollish = is_poll_message(msg) or getattr(msg, "fwd_from", None) is not None
        if not pollish:
            return msg, None

        last_exc = None
        for attempt in range(3):
            try:
                fresh = await client.get_messages(event.chat_id, ids=int(msg.id))
                if fresh is not None:
                    data = _quiz_data(fresh)
                    if data is not None:
                        if attempt:
                            self.db.log("INFO", f"Intake poll recovered after refresh: uid={event.sender_id}; msg_id={msg.id}; attempt={attempt+1}")
                        return fresh, data
            except Exception as exc:
                last_exc = exc
            if attempt < 2:
                await asyncio.sleep(0.35 * (attempt + 1))

        # Diagnostic only; the original forward can still be useful even if the
        # private message wrapper did not expose the Poll to Telethon immediately.
        op, omid = forwarded_origin(msg)
        self.db.log(
            "WARN",
            f"Intake poll not recognized: uid={event.sender_id}; private_msg_id={msg.id}; "
            f"media={type(getattr(msg,'media',None)).__name__}; "
            f"fwd_origin={op!r}:{omid}; refresh_error={last_exc!r}",
        )
        return msg, None

    async def handle(self, client, event) -> bool:
        if not event.is_private:
            return False
        uid = int(event.sender_id)
        # One user's messages are processed strictly in order: a quiz still being
        # processed can never be overtaken by the YAKUNLASH sent right after it.
        async with self._lock(uid):
            return await self._handle_locked(client, event, uid)

    async def _handle_locked(self, client, event, uid: int) -> bool:
        text = clean(event.raw_text or "").strip()

        if text.upper() == COMMAND_INFO:
            await self.info(client, event, uid)
            return True
        if text.upper() == COMMAND_FINISH:
            await self.finish(client, event, uid)
            return True

        msg = event.message

        # 1) Image intake. Use a FIFO queue so rapid batches do not overwrite
        # earlier images: image1->quiz1, image2->quiz2, ...
        if _is_image_message(msg):
            try:
                downloaded = await self._download_image(client, msg, self._image_path(uid, msg))
                if not downloaded:
                    await event.reply("❌ Rasmni qabul qilib bo‘lmadi. Qaytadan yuboring.")
                    return True
                self.db.intake_add_pending_image(uid, int(msg.id), str(downloaded))
                self._changed()
                st = self.db.intake_stats(uid)
                await event.reply(
                    "🖼 Rasm qabul qilindi. Keyingi viktorinaga biriktiriladi.\n"
                    f"Hozirgacha: {st['count']} ta viktorina.\n"
                    f"⏳ Kutilayotgan rasm: {st['pending_count']} ta\n"
                    "Yakunlash uchun YAKUNLASH yozing."
                )
            except Exception as exc:
                self.db.log("ERROR", f"Intake photo uid={uid}; msg_id={msg.id}: {exc}")
                await event.reply("❌ Rasmni saqlashda xatolik yuz berdi. Qaytadan yuboring.")
            return True

        # 2) Telegram quiz detection. For forwarded/shared polls, do not rely on
        # raw_text or a single Telethon object; refresh the exact message.
        msg, data = await self._refresh_quiz(client, event, msg)
        if data is None:
            return False

        question, options, poll, answers = data
        op, omid = forwarded_origin(msg)
        if op is not None:
            self.db.log(
                "INFO",
                f"Intake forwarded quiz detected: uid={uid}; private_msg_id={msg.id}; original={op!r}:{omid}; q={question[:90]}",
            )
        else:
            self.db.log(
                "INFO",
                f"Intake quiz detected: uid={uid}; private_msg_id={msg.id}; q={question[:90]}",
            )

        try:
            correct, solution, voted_now = await telegram_correct_index(
                client, event.chat_id, msg, poll, answers
            )
        except errors.FloodWaitError as exc:
            # RateLimiter normally consumes FloodWaitError itself. This branch is
            # a final safety net so the user never gets a misleading "bad quiz".
            wait = int(getattr(exc, "seconds", 1) or 1)
            self.db.log("WARN", f"Intake FloodWait escaped limiter uid={uid}; wait={wait}; msg_id={msg.id}")
            await event.reply(f"⏳ Telegram limiti: {wait} soniya kutaman, so‘ng viktorinani qayta ishlayman.")
            return True
        except errors.RPCError as exc:
            self.db.log(
                "WARN",
                f"Intake vote RPC failed uid={uid}; private_msg_id={msg.id}; "
                f"original={op!r}:{omid}; {type(exc).__name__}: {exc}",
            )
            await event.reply(
                "❌ Telegram viktorina natijasini olishga hozir ruxsat bermadi. "
                "Viktorinani qayta yuboring; bot original manbasini ham tekshiradi."
            )
            return True
        except Exception as exc:
            self.db.log(
                "WARN",
                f"Intake quiz failed uid={uid}; private_msg_id={msg.id}; "
                f"original={op!r}:{omid}; {type(exc).__name__}: {exc}",
            )
            await event.reply(
                "❌ Viktorina aniqlandi, lekin Telegramdan to‘g‘ri javobni olishning iloji bo‘lmadi. "
                "YAKUNLASH hali o‘chirmaydi — viktorinani qayta yuborishingiz mumkin."
            )
            return True

        if correct is None:
            await event.reply("❌ Telegram to‘g‘ri javobni qaytarmadi. Bu viktorinani qabul qila olmadim.")
            return True

        # Exact pairing: the image directly above this quiz (see _paired_image).
        try:
            pending_image = await self._paired_image(client, event, uid, msg)
        except Exception as exc:
            pending_image = ""
            self.db.log("WARN", f"Intake image pairing uid={uid}; quiz_msg_id={msg.id}: {type(exc).__name__}: {exc}")
        if pending_image:
            self.db.log("INFO", f"Intake paired image: uid={uid}; quiz_msg_id={msg.id}; image={Path(pending_image).name}")

        record = {
            "user_id": uid,
            "message_id": int(msg.id),
            "question": question,
            "options": options,
            "correct_index": int(correct),
            "explanation": clean(solution),
            "answer_source": "telegram_poll_results",
            "voted_now": bool(voted_now),
            "image_path": pending_image or "",
            "fingerprint": fingerprint(question, options),
        }

        if self.db.intake_has_fingerprint(uid, record["fingerprint"]):
            if pending_image:
                Path(pending_image).unlink(missing_ok=True)
            await event.reply("ℹ️ Bu viktorina shu yig‘imda avval qabul qilingan. Takror hisoblanmadi.")
            return True

        self.db.intake_add(uid, record)
        self._changed()
        st = self.db.intake_stats(uid)
        image_word = "rasmli" if pending_image else "rasmsiz"
        await event.reply(
            f"✅ {st['count']}-viktorina qabul qilindi ({image_word}).\n"
            f"📊 Rasmli: {st['with_image']} | Rasmsiz: {st['without_image']}\n"
            f"⏳ Kutilayotgan rasm: {st['pending_count']} ta\n"
            "INFO — holatni ko‘rish\nYAKUNLASH — barchasini bitta Word fayl qilish"
        )
        return True

    async def info(self, client, event, uid: int):
        st = self.db.intake_stats(uid)
        pending = "ha" if st["pending_count"] else "yo‘q"
        await event.reply(
            "📊 YIG‘IM HOLATI\n\n"
            f"Jami viktorina: {st['count']} ta\n"
            f"Rasmli: {st['with_image']} ta\n"
            f"Rasmsiz: {st['without_image']} ta\n"
            f"Kutilayotgan rasm: {pending} ({st['pending_count']} ta)\n\n"
            "Barchasini Word fayl qilish uchun YAKUNLASH yozing."
        )

    async def finish(self, client, event, uid: int):
        # Claim the batch first: it is removed from the DB in one transaction, so
        # it can never be added to the NEXT collection, whatever happens below.
        rows = self.db.intake_claim(uid)
        if not rows:
            self._drop_pending(uid)
            self._changed()
            await event.reply("ℹ️ Hozircha birorta viktorina qabul qilinmagan.")
            return

        await event.reply(f"⏳ {len(rows)} ta viktorinadan Word fayl tayyorlanmoqda...")
        from utils.exporter import export

        out_dir = self._user_dir(uid) / f"out_{int(time.time() * 1000)}"
        try:
            files = await asyncio.to_thread(export, rows, max(1, len(rows)), "quiz_test", out_dir)
            for path in files:
                await client.send_file(
                    event.chat_id,
                    str(path),
                    caption=f"✅ Yakunlandi: {len(rows)} ta viktorina",
                )
        except Exception as exc:
            # Nothing was delivered: put the batch back so no quiz is lost.
            self.db.log("ERROR", f"Intake finish uid={uid}: {type(exc).__name__}: {exc}")
            self.db.intake_restore(uid, rows)
            self._changed()
            await event.reply("❌ Word fayl yuborilmadi. Viktorinalar saqlab qolindi, YAKUNLASH ni qayta yozing.")
            return
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

        self._cleanup_images(rows)
        self._drop_pending(uid)
        self._changed()
        await event.reply("✅ Tayyor. Yangi yig‘im boshlandi — yuborilgan viktorinalar endi keyingi Wordga qo‘shilmaydi.")

    def _cleanup_images(self, rows):
        for row in rows:
            path = row.get("image_path") or ""
            if path:
                Path(path).unlink(missing_ok=True)
