# Telegram Quiz UserBot — Standalone

Bu loyiha avvalgi Quiztime botdan mustaqil. U faqat o'z repositorysi, SQLite bazasi va Telegram user sessionidan foydalanadi.

## Asosiy imkoniyatlar

- Streamlit boshqaruv paneli
- Telethon orqali Telegram UserBot
- Groq API orqali AI operator
- Operator roli `config/agent_prompt.txt` orqali boshqariladi
- Buyurtma suhbatlarini AI orqali olib borish
- Kanal/guruh manbalarini saqlash
- Quiz fingerprint/deduplication
- SQLite storage
- TXT/JSON eksport
- Rate limiter asoslari
- Telegram FLOOD_WAIT holatini hisobga oladigan arxitektura

## Ishga tushirish

```bash
pip install -r requirements.txt
streamlit run app.py
```

Telegram API ma'lumotlari uchun `my.telegram.org` orqali API ID va API HASH oling.

Groq API keyni Streamlit panelidan kiriting yoki `GROQ_API_KEY` environment variable sifatida bering.

## UserBotni ishga tushirish

Streamlit UI boshqaruv uchun. Doimiy UserBot workerini alohida process/hostingda ishga tushirish tavsiya qilinadi:

```bash
python -c "from userbot.client import UserBotController; UserBotController().start()"
```

Birinchi ishga tushishda Telegram login/OTP jarayoni bo'ladi.

## Muhim

Telegram rate limitlarini chetlab o'tish uchun agressiv parallel request, proxy rotation yoki boshqa bypass ishlatilmaydi. Scanner deduplication, throttling va `FLOOD_WAIT`ni kutish mexanizmi bilan ishlashi kerak.

### Native Telegram Quiz

Telegramdagi anonim quizdan API orqali olingan ma'lumotlarda correct answer har doim oddiy xabar obyektida mavjud bo'lmasligi mumkin. Shuning uchun native quizning to'g'ri javobini olish/publish qilish qismi Telethon versiyasi va API imkoniyatlariga qarab alohida adapter bilan yakuniy test qilinishi kerak. Noto'g'ri javobni AI bilan taxmin qilib belgilash default holatda qilinmaydi.
