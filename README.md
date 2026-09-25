# Telegram Quiz UserBot PRO

Streamlit + Telethon asosidagi alohida Telegram UserBot loyihasi.

## Asosiy arxitektura

- Background Telethon UserBot
- Private-message operator (Groq ishlatadi)
- Kanal/guruh scanner
- Native Telegram **Quiz** poll aniqlash
- Har bir quiz uchun original `source` va Telegram `message_id` saqlash
- **Correct answer AI bilan yechilmaydi**
- Scanner `messages.sendVote` orqali shu quizga bir marta ovoz beradi
- Telegram qaytargan `pollResults` ichidagi `correct=True` flagdan to‘g‘ri variant olinadi
- Agar akkaunt allaqachon ovoz bergan bo‘lsa va `REVOTE_NOT_ALLOWED` qaytsa, bot qayta ovoz bermaydi; `messages.getPollResults` orqali natijani oladi
- Telegram `solution` mavjud bo‘lsa `Izoh:` sifatida saqlanadi; AI izoh yozmaydi
- Fingerprint/dedup
- URL, `t.me`, `telegram.me`, `@username` reklama qismlarini tozalash
- UTF-8 mojibake recovery (`â€˜`, `â€™`, `â€‘` kabi buzilishlar)
- Telethon `TextWithEntities` va ichma-ich text obyektlarini oddiy stringga aylantirish
- TXT export: `1. Savol`, `A)`, `*B)`, `Izoh:` faqat mavjud bo‘lsa
- Optional native Quiz publisher
- SQLite persistence
- Scanner start/stop state va FloodWait logging

## Correct-answer oqimi

```text
Telegram Quiz message
        ↓
source + message_id + poll.answers
        ↓
messages.sendVote(1 ta option)
        ↓
Telegram pollResults
        ↓
PollAnswerVoters.correct=True
        ↓
A/B/C/D index
        ↓
SQLite
        ↓
TXT / optional publisher
```

Bu scanner savolni Groq yordamida taxmin qilmaydi. Telegram `correct` flag qaytarmasa, quiz **verified sifatida saqlanmaydi**.

## Groq

`GROQ_API_KEY` va `GROQ_API_KEY1` ... `GROQ_API_KEY9` pooli faqat operatorning suhbat javoblari uchun ishlatiladi. 429 bo‘lsa pool keyni almashtiradi. Bu Telegram limitlarini chetlab o‘tish mexanizmi emas.

## Telegram cheklovlari

Scanner `messages.sendVote`ni faqat bir marta yuboradi. `REVOTE_NOT_ALLOWED` holatida qayta ovoz berishga urinmaydi. Kanalga a’zo bo‘lish, subscriber-only poll, country restriction yoki yopilgan poll kabi Telegram cheklovlari bajarilmasa, quiz skip qilinadi va sabab logga yoziladi.

## TXT

Misol:

```text
1. Qaysi gapda imloviy xatolik uchramaydi?
A) O‘sha vaqtlarda...
B) Chap tomonda...
*C) Qizning yuragi...
D) Bog‘ga kirdim...
Izoh: Telegram quiz solution bo‘lsa shu yerda chiqadi.
```

`TextWithEntities(...)` repri TXTga yozilmaydi. Fayl UTF-8 encodingda yaratiladi.
