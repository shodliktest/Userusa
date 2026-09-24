# Telegram Quiz UserBot Pro

Alohida loyiha: Streamlit + Telethon + Groq.

- Background UserBot
- Groq `GROQ_API_KEY` + `GROQ_API_KEY1` ... `GROQ_API_KEY9` pool
- 429/rate-limit bo'lsa key cooldown va keyingisiga o'tish
- Kuchli buyurtma operatori prompti
- Kanal/guruhdan native Telegram quiz scan
- Manba bo'yicha target soni va TXT fayl hajmi
- Fingerprint/dedup
- URL/t.me/telegram.me/@username reklamalarini tozalash
- Native correct answer ko'rinsa ishlatish; aks holda Groq fallback
- Past confidence quiz saqlanmaydi
- TXT: `1. Savol`, `A)`, `*B)`, `Izoh:` faqat mavjud bo'lsa
- Native Quiz publisher adapteri mavjud

Telegram MTProto arbitrary anonymous quizlarning original correct answerini har doim oddiy poll obyektida bermaydi. Shu sabab native flag birinchi tekshiriladi, keyin Groq fallback ishlaydi. AI javobi ham ishonch chegarasidan past bo'lsa quiz verified sifatida saqlanmaydi.

Telegram API limitlarini bypass qilish uchun proxy/key rotation ishlatilmaydi; Groq key rotation faqat Groq limitlarida ishlaydi.
