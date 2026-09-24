import random
from telethon import functions,types
async def publish_quiz(client,chat,q,options,correct,explanation=''):
 answers=[types.PollAnswer(text=types.TextWithEntities(text=str(x),entities=[]),option=bytes([i])) for i,x in enumerate(options)]
 poll=types.Poll(id=random.getrandbits(63),closed=False,public_voters=False,multiple_choice=False,quiz=True,question=types.TextWithEntities(text=str(q)[:300],entities=[]),answers=answers)
 media=types.InputMediaPoll(poll=poll,correct_answers=[bytes([correct])],solution=(explanation[:200] if explanation else None))
 return await client(functions.messages.SendMedia(peer=await client.get_input_entity(chat),media=media,message='',random_id=random.getrandbits(63)))
