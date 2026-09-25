"""Private-chat quiz intake.

Users can send a sequence of:
    photo -> anonymous Telegram quiz -> photo -> quiz -> ...

The next quiz consumes the latest pending photo. A quiz without a photo is also
accepted. INFO reports the current session; YAKUNLASH exports the whole session
as one DOCX and sends it back to that same user.

Answer extraction is Telegram-only: the exact private-chat message_id is voted
once and the returned Telegram poll results are used. No AI is called here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from telethon import errors

from userbot.scanner import clean, fingerprint, poll_from_message, telegram_correct_index


COMMAND_INFO = "INFO"
COMMAND_FINISH = "YAKUNLASH"


def _is_quiz(msg: Any) -> bool:
    poll = poll_from_message(msg)
    return bool(poll is not None and getattr(poll, "quiz", False))


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


class IntakeManager:
    def __init__(self, db, base_dir="data/intake"):
        self.db = db
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: int | str) -> Path:
        p = self.base / str(user_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def handle(self, client, event) -> bool:
        """Return True when this event was consumed by the intake workflow."""
        if not event.is_private:
            return False

        uid = int(event.sender_id)
        text = clean(event.raw_text or "").strip()

        # Explicit chat commands must not fall through to the Groq operator.
        if text.upper() == COMMAND_INFO:
            await self.info(client, event, uid)
            return True
        if text.upper() == COMMAND_FINISH:
            await self.finish(client, event, uid)
            return True

        msg = event.message

        # Photo comes before its related quiz. Save it and wait for the next quiz.
        is_image = getattr(msg, "photo", None) is not None
        document = getattr(msg, "document", None)
        if not is_image and document is not None:
            mime = str(getattr(document, "mime_type", "") or "").lower()
            is_image = mime.startswith("image/")
        if is_image:
            suffix = ".jpg" if getattr(msg, "photo", None) is not None else ".img"
            path = self._user_dir(uid) / f"pending_{msg.id}{suffix}"
            try:
                old_pending = self.db.intake_take_pending_image(uid)
                if old_pending:
                    try:
                        Path(old_pending).unlink(missing_ok=True)
                    except Exception:
                        pass
                downloaded = await client.download_media(msg, file=str(path))
                if not downloaded:
                    await event.reply("❌ Rasmni qabul qilib bo‘lmadi. Qaytadan yuboring.")
                    return True
                self.db.intake_set_pending_image(uid, str(downloaded))
                st = self.db.intake_stats(uid)
                await event.reply(
                    f"🖼 Rasm qabul qilindi. Keyingi yuboradigan viktorinangizga biriktiriladi.\n"
                    f"Hozirgacha: {st['count']} ta viktorina.\n"
                    f"Yakunlash uchun YAKUNLASH yozing."
                )
            except Exception as exc:
                self.db.log("ERROR", f"Intake photo {uid}: {exc}")
                await event.reply("❌ Rasmni saqlashda xatolik yuz berdi. Qaytadan yuboring.")
            return True

        data = _quiz_data(msg)
        if data is None:
            # Text other than INFO/YAKUNLASH belongs to the normal operator.
            return False

        question, options, poll, answers = data
        try:
            correct, solution, voted_now = await telegram_correct_index(
                client, event.chat_id, msg, poll, answers
            )
        except errors.RPCError as exc:
            self.db.log("WARN", f"Intake vote failed uid={uid}, msg_id={msg.id}: {type(exc).__name__}: {exc}")
            await event.reply(
                "❌ Telegram bu viktorinaning natijasini o‘qishga ruxsat bermadi. "
                "Viktorinani qayta yuboring."
            )
            return True
        except Exception as exc:
            self.db.log("WARN", f"Intake quiz failed uid={uid}, msg_id={msg.id}: {exc}")
            await event.reply(
                "❌ Telegramdan to‘g‘ri javobni olishning iloji bo‘lmadi. "
                "Viktorinani qayta yuboring."
            )
            return True

        if correct is None:
            await event.reply("❌ Telegram to‘g‘ri javobni qaytarmadi. Bu viktorinani qabul qila olmadim.")
            return True

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

        # Avoid accidentally counting the same forwarded quiz twice in one session.
        if self.db.intake_has_fingerprint(uid, record["fingerprint"]):
            if pending_image:
                try:
                    Path(pending_image).unlink(missing_ok=True)
                except Exception:
                    pass
            await event.reply("ℹ️ Bu viktorina shu yig‘imda avval qabul qilingan. Takror hisoblanmadi.")
            return True

        self.db.intake_add(uid, record)
        st = self.db.intake_stats(uid)
        image_word = "rasmli" if pending_image else "rasmsiz"
        await event.reply(
            f"✅ {st['count']}-viktorina qabul qilindi ({image_word}).\n"
            f"📊 Rasmli: {st['with_image']} | Rasmsiz: {st['without_image']}\n"
            f"INFO — holatni ko‘rish\nYAKUNLASH — barchasini bitta Word fayl qilish"
        )
        return True

    async def info(self, client, event, uid: int):
        st = self.db.intake_stats(uid)
        pending = "ha" if st["pending_image"] else "yo‘q"
        await event.reply(
            "📊 YIG‘IM HOLATI\n\n"
            f"Jami viktorina: {st['count']} ta\n"
            f"Rasmli: {st['with_image']} ta\n"
            f"Rasmsiz: {st['without_image']} ta\n"
            f"Kutilayotgan rasm: {pending}\n\n"
            "Barchasini Word fayl qilish uchun YAKUNLASH yozing."
        )

    async def finish(self, client, event, uid: int):
        rows = self.db.intake_items(uid)
        if not rows:
            pending = self.db.intake_take_pending_image(uid)
            if pending:
                try:
                    Path(pending).unlink(missing_ok=True)
                except Exception:
                    pass
            await event.reply("ℹ️ Hozircha birorta viktorina qabul qilinmagan.")
            return

        await event.reply(f"⏳ {len(rows)} ta viktorinadan Word fayl tayyorlanmoqda...")
        from utils.exporter import export

        name = _safe_name(rows[0].get("question") or "quizlar")
        try:
            files = export(rows, max(1, len(rows)), name)
            for path in files:
                await client.send_file(
                    event.chat_id,
                    str(path),
                    caption=f"✅ Yakunlandi: {len(rows)} ta viktorina",
                )
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            self._cleanup_images(rows)
            self.db.intake_clear(uid)
            await event.reply("✅ Tayyor. Yig‘im tozalandi, yangi viktorinalarni yuborishingiz mumkin.")
        except Exception as exc:
            self.db.log("ERROR", f"Intake finish uid={uid}: {exc}")
            await event.reply("❌ Word fayl yaratishda xatolik yuz berdi. Yig‘ilgan viktorinalar o‘chirilmagan.")

    def _cleanup_images(self, rows):
        for row in rows:
            path = row.get("image_path") or ""
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass
