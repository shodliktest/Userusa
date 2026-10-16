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


### Telegram rate limiting

Scanner and private-chat quiz intake use `utils/rate_limiter.py`. Voting is intentionally conservative (3 seconds minimum between vote RPCs). If Telegram returns `FloodWaitError`, the bot waits for Telegram's requested duration plus a small safety margin and retries instead of counting the quiz as an answer failure. A final unrecoverable FloodWait is still surfaced in the log.

`Javob xatosi` means the bot could not obtain Telegram's authoritative `PollResults.correct` value; it does not mean the quiz answer itself was wrong.


## QuizBot link -> alohida Word (yangi modul)

- `userbot/quizbot_word.py` foydalanuvchi shaxsiy chatga `https://t.me/QuizBot?start=...` linkini yuborganda alohida sessiya boshlaydi.
- Har bir foydalanuvchi uchun mustaqil yig‘im yuritiladi; savollar boshqa yig‘imlarga qo‘shilmaydi.
- Modul mavjud Telethon klientidan foydalanadi; ikkinchi Telegram sessiyasi ochmaydi.
- Savollar Telegram native Quiz Poll bo‘lsa, Telegram natijasidan to‘g‘ri javobni olishga urinadi. AI javob taxmin qilmaydi.
- Rasmlar bot dialogida savoldan oldin kelganida yuklab olinadi va DOCX ichiga joylanadi.
- Natija fayllari `data/quizbot_word/` ichiga yoziladi va link yuborgan foydalanuvchiga yuboriladi.

**Eslatma:** Telegram botlari o‘zgaruvchan suhbat oqimidan foydalanishi mumkin. Modul Start/Next kabi aniq navigatsiya tugmalarini bosishga urinadi, ammo barcha QuizBot test turlari bilan jonli sinov qilinmaguncha har bir havola, rasm yoki yakunlash holati kafolatlanmaydi. Agar QuizBot testni boshlash uchun qo‘shimcha tasdiq yoki qo‘llab-quvvatlanmaydigan tugma talab qilsa, log orqali tekshirish kerak.
