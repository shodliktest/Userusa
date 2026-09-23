from ai.operator import Operator

def register_handlers(client,db):
    operator=Operator()
    history={}

    @client.on(__import__("telethon").events.NewMessage(incoming=True))
    async def incoming(event):
        if not event.is_private:
            return
        text=(event.raw_text or "").strip()
        if not text:
            return
        uid=str(event.sender_id)
        h=history.setdefault(uid,[])
        try:
            answer=operator.reply(h,text)
            h.extend([{"role":"user","content":text},{"role":"assistant","content":answer}])
            h[:] = h[-12:]
            await event.reply(answer)
        except Exception as e:
            db.add_log("ERROR",f"AI reply: {e}")
            await event.reply("Hozir javob berishda texnik xatolik yuz berdi. Iltimos, birozdan keyin qayta yozing.")
