import asyncio, threading
from config.settings import load_settings
from storage.database import Database
from userbot.handlers import register_handlers

HEARTBEAT_INTERVAL=15  # soniya

class UserBotController:
    def __init__(self):
        self.settings=load_settings()
        self.db=Database()
        self.client=None

    async def _heartbeat_loop(self):
        me=None
        try:
            me=await self.client.get_me()
        except Exception:
            pass
        label=f"@{me.username}" if me and me.username else (str(me.id) if me else "")
        while True:
            try:
                connected=self.client.is_connected()
                self.db.set_heartbeat("running" if connected else "reconnecting", label)
            except Exception as e:
                self.db.set_heartbeat("error", str(e))
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def run(self):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        api_id=int(self.settings["api_id"])
        api_hash=self.settings["api_hash"]
        session_string=self.settings.get("session_string","")
        if not session_string:
            self.db.set_heartbeat("error","TELEGRAM_SESSION_STRING sozlanmagan (secrets)")
            raise RuntimeError(
                "TELEGRAM_SESSION_STRING topilmadi. Avval bir marta mahalliyda "
                "login qilib, session stringni generatsiya qiling va uni Streamlit "
                "secrets ichiga qo'shing (pastdagi generate_session_string.py skriptiga qarang)."
            )

        # StringSession diskka yozmaydi — Streamlit Cloud'ning vaqtinchalik
        # fayl tizimida sessiya yo'qolib qolishining oldini oladi.
        self.client=TelegramClient(StringSession(session_string), api_id, api_hash)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            self.db.set_heartbeat("error","Session string yaroqsiz/muddati o'tgan")
            raise RuntimeError("Session string bilan avtorizatsiya muvaffaqiyatsiz. Session stringni qayta generatsiya qiling.")

        register_handlers(self.client,self.db)
        self.db.set_heartbeat("running","")
        hb_task=asyncio.create_task(self._heartbeat_loop())
        try:
            await self.client.run_until_disconnected()
        finally:
            hb_task.cancel()
            self.db.set_heartbeat("stopped","")

    def start(self):
        """Bloklovchi chaqiruv — background thread ichida ishga tushiriladi."""
        try:
            asyncio.run(self.run())
        except Exception as e:
            self.db.set_heartbeat("error",str(e))
            raise


_worker_thread=None
_worker_lock=threading.Lock()

def ensure_worker_started():
    """QuizMarker botidagi naqshga o'xshab: Streamlit rerun bo'lganda ham
    faqat bitta background thread ishlab tursin. app.py shu funksiyani
    chaqiradi; ikkinchi marta chaqirilsa hech narsa qilmaydi."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return False  # allaqachon ishlayapti
        controller=UserBotController()
        _worker_thread=threading.Thread(target=controller.start, daemon=True, name="userbot-worker")
        _worker_thread.start()
        return True

def worker_is_alive():
    return _worker_thread is not None and _worker_thread.is_alive()
