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
from pathlib import Path
from typing import Any

from telethon import errors

from userbot.scanner import (
    clean,
    fingerprint,
    forwarded_origin,
    is_poll_message,
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
    def __init__(self, db, base_dir="data/intake"):
        self.db = db
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

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
            suffix = ".jpg" if getattr(msg, "photo", None) is not None else ".img"
            path = self._user_dir(uid) / f"pending_{msg.id}{suffix}"
            try:
                downloaded = await client.download_media(msg, file=str(path))
                if not downloaded:
                    await event.reply("❌ Rasmni qabul qilib bo‘lmadi. Qaytadan yuboring.")
                    return True
                self.db.intake_add_pending_image(uid, int(msg.id), str(downloaded))
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

        # Pairing is deliberately message-ID aware. If the immediately previous
        # private-chat message is a single image, that exact image belongs to this
        # quiz (the same rule used by the channel scanner). Only if there is no
        # immediate image do we fall back to the FIFO queue.
        pending_image = ""
        try:
            previous = await client.get_messages(event.chat_id, ids=int(msg.id) - 1) if int(msg.id) > 1 else None
            if previous is not None and _is_image_message(previous):
                pending_image = self.db.intake_take_pending_image_for_message(uid, int(previous.id))
                if not pending_image:
                    suffix = ".jpg" if getattr(previous, "photo", None) is not None else ".img"
                    pth = self._user_dir(uid) / f"pending_{previous.id}{suffix}"
                    downloaded = await client.download_media(previous, file=str(pth))
                    if downloaded:
                        pending_image = str(downloaded)
                        self.db.log("INFO", f"Intake paired exact previous image: uid={uid}; image_msg_id={previous.id}; quiz_msg_id={msg.id}")
            if not pending_image:
                pending_image = self.db.intake_take_pending_image(uid)
        except Exception as exc:
            self.db.log("WARN", f"Intake image pairing uid={uid}; quiz_msg_id={msg.id}: {exc}")
            pending_image = self.db.intake_take_pending_image(uid)

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
        rows = self.db.intake_items(uid)
        if not rows:
            for pending in self.db.intake_pending_paths(uid):
                Path(pending).unlink(missing_ok=True)
            self.db.intake_clear(uid)
            await event.reply("ℹ️ Hozircha birorta viktorina qabul qilinmagan.")
            return

        await event.reply(f"⏳ {len(rows)} ta viktorinadan Word fayl tayyorlanmoqda...")
        from utils.exporter import export

        try:
            files = export(rows, max(1, len(rows)), "quiz_test")
            for path in files:
                await client.send_file(
                    event.chat_id,
                    str(path),
                    caption=f"✅ Yakunlandi: {len(rows)} ta viktorina",
                )
                path.unlink(missing_ok=True)
            self._cleanup_images(rows)
            for pending in self.db.intake_pending_paths(uid):
                Path(pending).unlink(missing_ok=True)
            self.db.intake_clear(uid)
            await event.reply("✅ Tayyor. Yig‘im tozalandi, yangi viktorinalarni yuborishingiz mumkin.")
        except Exception as exc:
            self.db.log("ERROR", f"Intake finish uid={uid}: {exc}")
            await event.reply("❌ Word fayl yaratishda xatolik yuz berdi. Yig‘ilgan viktorinalar o‘chirilmagan.")

    def _cleanup_images(self, rows):
        for row in rows:
            path = row.get("image_path") or ""
            if path:
                Path(path).unlink(missing_ok=True)
