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


## v15 o'zgarishlari

### 1. Rasm + undan keyingi viktorina (chat va kanal)
- Juftlash qoidasi: viktorinadan **darhol oldingi** xabar rasm bo'lsa, o'sha rasm shu viktorinaga biriktiriladi (masalan id 12 rasm, id 13 viktorina).
- Kanal/guruhda `id-1` taxmin qilinmaydi: eng yaqin oldingi mavjud xabar olinadi (o'chirilgan id lar uzilish bo'lmaydi). Eski `Path` import xatosi tuzatildi (rasmlar shu sabab olinmagan edi).
- Private chatda botning o'z javoblari ("Rasm qabul qilindi") hisobga olinmaydi, shuning uchun rasm → bot javobi → viktorina ham to'g'ri juftlanadi.
- Rasm ustida viktorina bo'lmasa, viktorina rasmsiz qoladi (endi "navbat bo'yicha taxmin" yo'q).
- Scanner rasm yo'li bazaga (`quizzes.image_path`) yoziladi, shuning uchun Export tabida ham rasmlar chiqadi.
- `-100...` ko'rinishidagi kanal ID lari to'g'ri `int` ga o'tkaziladi.

### 2. YAKUNLASH dan keyin yig'im alohida
- `YAKUNLASH` yig'imni bazadan bitta tranzaksiyada **oldin ajratib oladi**, so'ng Word yuboradi. Yuborilgan viktorinalar keyingi Wordga hech qachon qo'shilmaydi.
- Yuborish xato bo'lsa viktorinalar qaytariladi (yo'qolmaydi), qayta `YAKUNLASH` yozish kifoya.
- Bir foydalanuvchi xabarlari tartib bilan ishlanadi: YAKUNLASH dan oldin yuborilgan, hali qayta ishlanayotgan viktorina ham shu Wordga kiradi.
- Word fayllari har safar alohida vaqtinchalik papkada yaratiladi (fayl nomi to'qnashmaydi).

### 3. Ma'lumotlar Telegram storage kanalida
1. Yopiq kanal oching (userbot akkaunti egasi/admin bo'lsin).
2. `STORAGE_CHANNEL = "-100..."` (yoki `@kanal`) ni secrets ga qo'shing.
3. Bot har ~2 daqiqada (o'zgarish bo'lsa) `userbot_state_*.zip` yuklaydi: baza (manbalar, fingerprintlar, viktorinalar, checkpointlar, yig'imlar) + rasmlar. Oxirgi 3 ta zaxira saqlanadi.
4. Qayta ishga tushganda (lokal baza bo'sh bo'lsa) eng so'nggi zaxira avtomatik tiklanadi va ish shundan davom etadi.
- `data/scanner_images` 150 MB dan oshsa, zaxiraga kiritilmaydi (log ogohlantiradi); baza doim kiradi.
- Lokal baza bo'sh bo'lmasa tiklash bo'lmaydi (lokal ma'lumot ustun).


## v16 o'zgarishlari

### Telegram limitlari (FloodWait) — kutadi va davom etadi
- Har qanday FloodWait/SlowMode (soniyadan soatgacha, eng ko'pi 24 soat) kutiladi va **aynan shu so'rov** qayta yuboriladi; quiz tashlab ketilmaydi, skan to'xtamaydi.
- Chat tarixini o'qish ham tiklanadigan: limit tugagach shu xabardan davom etadi.
- Rasm yuklash, DOCX/native yuborish ham limiter orqali ishlaydi.
- Kutish vaqtida panelda "⏳ ... ~HH:MM da davom etadi" ko'rinadi; **Stop** kutishni ~1 soniyada to'xtatadi.
- Qayta urinib bo'ladigan xatoda checkpoint shu quizdan oldin to'xtaydi, keyingi ishga tushirishda qayta uriniladi.
- Ulanish uzilishlari (timeout/connection) 2s, 8s, 18s... pauza bilan qayta uriniladi.

### Konsol
- Barcha loglar terminalga ham chiqadi (o'chirish: `LOG_TO_CONSOLE=0`), har 200 xabarda `PROGRESS` qatori, Telethon'ning o'z flood-sleep xabarlari ham.

### QuizBot → Word (rasmlardagi oqim bo'yicha)
`/start <payload>` → **I am ready!** bosiladi → savollar native quiz sifatida kelib, har biriga javob beriladi → "paused ... stopped answering" chiqsa **Resume Quiz** bosiladi (Stop Quiz hech qachon) → **Try again** chiqsa test tugagan: bitta Word fayl link yuborilgan chatga jo'natiladi.
- `[22/40]` prefiksi savoldan olib tashlanadi; fayl nomi/sarlavha test nomidan olinadi.
- Rasmli savol: rasm xabari poll'dan **darhol oldin** bo'lsa biriktiriladi.
- Bir vaqtda bitta QuizBot testi (qolganlari navbatda). Bekor qilish: `BEKOR`.

### Word shabloni (kanal/guruh skani, chat va QuizBot uchun bir xil)
```
1. Savol
A) variant
B) variant  ✓ (to'g'ri javob yashil)
[rasm — variantlardan KEYIN, markazda]
Izoh: ...
```
Rasm sahifaga sig'adigan qilib kichraytiriladi (eni ≤ 15.5 sm, bo'yi ≤ 11 sm).
