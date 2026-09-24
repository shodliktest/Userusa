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

## Sozlash (barchasi Streamlit Secrets orqali)

Hech qanday API kalit yoki sessiya UI'dan kiritilmaydi yoki diskka yozilmaydi.
Barcha maxfiy qiymatlar Streamlit Secrets orqali beriladi.

1. `my.telegram.org` orqali `TELEGRAM_API_ID` va `TELEGRAM_API_HASH` oling.
2. Session string generatsiya qiling (mahalliy kompyuteringizda, bir marta):
   ```bash
   pip install telethon
   python generate_session_string.py
   ```
   Telefon raqam va OTP kodni so'raydi, so'ngra `TELEGRAM_SESSION_STRING` qiymatini chiqaradi.
3. `.streamlit/secrets.toml.example` faylini `.streamlit/secrets.toml` deb nusxalang
   (mahalliy sinov uchun) va qiymatlarni to'ldiring; yoki Streamlit Cloud'da
   **App → Settings → Secrets** bo'limiga xuddi shu formatda joylashtiring:
   ```toml
   TELEGRAM_API_ID = "..."
   TELEGRAM_API_HASH = "..."
   TELEGRAM_SESSION_STRING = "..."
   GROQ_API_KEY = "..."
   ```
   Model nomi kodning ichida (`config/settings.py`) qattiq yozilgan — alohida sozlash shart emas.
4. Ishga tushiring:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

## UserBot qanday ishlaydi

UserBot alohida process sifatida emas, Streamlit ilovasi ochilganda **background
thread** sifatida avtomatik ishga tushadi (QuizMarker botidagi thread+polling
naqshiga o'xshab). Sahifa yuqorisidagi holat ko'rsatkichi (🟢/🟡/🔴/⚪) worker
tirikligini har safar sahifa yangilanganda ko'rsatadi.

Diqqat: Streamlit Community Cloud ilovani harakatsizlikdan keyin "uxlatishi"
yoki qayta deploy qilishi mumkin — bunday holatda thread ham qayta boshlanadi
va sahifa birinchi ochilganda biroz sekinroq javob berishi mumkin.

## Muhim

Telegram rate limitlarini chetlab o'tish uchun agressiv parallel request, proxy rotation yoki boshqa bypass ishlatilmaydi. Scanner deduplication, throttling va `FLOOD_WAIT`ni kutish mexanizmi bilan ishlashi kerak.

### Native Telegram Quiz

Telegramdagi anonim quizdan API orqali olingan ma'lumotlarda correct answer har doim oddiy xabar obyektida mavjud bo'lmasligi mumkin. Shuning uchun native quizning to'g'ri javobini olish/publish qilish qismi Telethon versiyasi va API imkoniyatlariga qarab alohida adapter bilan yakuniy test qilinishi kerak. Noto'g'ri javobni AI bilan taxmin qilib belgilash default holatda qilinmaydi.
