import hashlib, json, asyncio
from telethon import errors

def quiz_fingerprint(question,options,correct_index):
    raw=json.dumps({"q":question.strip(),"o":[x.strip() for x in options],"c":correct_index},
                   ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

async def scan_source(client,db,source,limit=None):
    count=0
    async for msg in client.iter_messages(source,limit=limit):
        # Native Telegram quiz/poll ma'lumotlarini olish
        poll=getattr(msg,"poll",None)
        if not poll:
            continue
        quiz=getattr(poll,"quiz",False)
        answers=getattr(poll,"answers",None)
        question=getattr(poll,"question",None)
        if not quiz or not question or not answers:
            continue

        # Telegram API'da poll answer obyektlari mavjud; correct option ayrim klient/API javoblarida ko'rinmasligi mumkin.
        options=[]
        for a in answers:
            txt=getattr(a,"text","")
            options.append(getattr(txt,"text",str(txt)))

        correct=None
        fp=quiz_fingerprint(question,options,correct)
        if db.fingerprint_exists(fp):
            continue
        db.save_fingerprint(fp,source,msg.id)
        db.save_quiz({
            "fingerprint":fp,"source":str(source),"message_id":msg.id,
            "question":question,"options":options,"correct_index":correct
        })
        count+=1
        await asyncio.sleep(0.05)
    return count
