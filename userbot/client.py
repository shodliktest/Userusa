import asyncio
from pathlib import Path
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
        api_id=int(self.settings["api_id"])
        api_hash=self.settings["api_hash"]
        session=self.settings.get("session_name","quiz_userbot")
        self.client=TelegramClient(session,api_id,api_hash)
        await self.client.start(phone=self.settings.get("phone") or None)
        register_handlers(self.client,self.db)
        self.db.set_heartbeat("running","")
        hb_task=asyncio.create_task(self._heartbeat_loop())
        try:
            await self.client.run_until_disconnected()
        finally:
            hb_task.cancel()
            self.db.set_heartbeat("stopped","")

    def start(self):
        try:
            asyncio.run(self.run())
        except Exception as e:
            self.db.set_heartbeat("error",str(e))
            raise
