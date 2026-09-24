import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
api=int(input('API ID: '));h=input('API HASH: ');phone=input('Phone: ')
async def main():
 c=TelegramClient(StringSession(),api,h);await c.start(phone=phone);print(c.session.save());await c.disconnect()
asyncio.run(main())
