import asyncio
from pathlib import Path
from config.settings import load_settings
from storage.database import Database
from userbot.handlers import register_handlers

class UserBotController:
    def __init__(self):
        self.settings=load_settings()
        self.db=Database()
        self.client=None

    async def run(self):
        from telethon import TelegramClient
        api_id=int(self.settings["api_id"])
        api_hash=self.settings["api_hash"]
        session=self.settings.get("session_name","quiz_userbot")
        self.client=TelegramClient(session,api_id,api_hash)
        await self.client.start(phone=self.settings.get("phone") or None)
        register_handlers(self.client,self.db)
        await self.client.run_until_disconnected()

    def start(self):
        asyncio.run(self.run())
