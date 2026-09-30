# Telegram Quiz UserBot Pro — Full

## Imkoniyatlar
- Streamlit boshqaruv paneli
- Telethon UserBot
- Groq operator (10 tagacha key)
- Anonim Telegram quiz/viktorinalarni kanal/guruhdan olish
- Telegram `pollResults` orqali correct answer; AI quiz javobini topmaydi
- Belgilangan miqdorda yoki kanal/guruh tarixini boshidan oxirigacha skanerlash
- Scanner fingerprint orqali takroriy quizlarni o'tkazib yuborish
- Private chat: rasm -> viktorina yoki rasmsiz viktorina qabul qilish
- INFO va YAKUNLASH
- Rasmni savoldan oldin DOCX ga joylash
- Native Telegram Quiz sifatida publish qilish
- DOCX ni belgilangan kanal/guruhga yuborish
- UTF-8/mojibake tuzatish va reklama URL/@username larini tozalash

## Secrets
`.streamlit/secrets.toml`:

```toml
TELEGRAM_API_ID = 123456
TELEGRAM_API_HASH = "..."
TELEGRAM_PHONE = "+998..."
TELEGRAM_SESSION_STRING = "..."
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY = "..."
GROQ_API_KEY1 = "..."
GROQ_API_KEY2 = "..."
```

`GROQ_API_KEY` dan `GROQ_API_KEY9` gacha qo'llab-quvvatlanadi.

## Private chat
1. Rasm yuboring.
2. Uning ostidagi Telegram quizni yuboring.
3. Bot quizni Telegramning o'zidan tekshiradi va qabul qiladi.
4. Istalgancha quiz yuborish mumkin.
5. `INFO` — yig'im holati.
6. `YAKUNLASH` — barcha yig'ilgan quizlarni bitta DOCX qilib shu chatga qaytaradi.

Scanner avval olgan quizni user private chat orqali yuborsa ham private intake uni qabul qiladi; scanner fingerprinti private intake'ni bloklamaydi.

## Ishga tushirish
```bash
pip install -r requirements.txt
streamlit run app.py
```
