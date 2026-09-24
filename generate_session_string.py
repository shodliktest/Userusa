"""
Bir martalik skript: Telegram StringSession generatsiya qilish uchun.

Buni Streamlit Cloud'da EMAS, o'z kompyuteringizda (yoki istalgan joyda
interaktiv terminal bor joyda) ishga tushiring. Telefon raqami va OTP
kodni so'raydi, so'ngra sessiya stringini chop etadi.

Ishga tushirish:
    pip install telethon
    python generate_session_string.py

Chiqadigan qatorni to'liq nusxalab, Streamlit'ning "Secrets" bo'limiga
TELEGRAM_SESSION_STRING sifatida joylashtiring. Bu qatorni hech kim bilan
ulashmang — u sizning Telegram akkauntingizga to'liq kirish huquqini beradi.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("Telegram API ID: ").strip())
api_hash = input("Telegram API HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\n=== TELEGRAM_SESSION_STRING (buni Streamlit secrets'ga joylashtiring) ===\n")
    print(session_string)
    print("\n===========================================================\n")
    print("OGOHLANTIRISH: bu qatorni hech kim bilan ulashmang.")
