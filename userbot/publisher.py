from telethon.tl.types import Poll, PollAnswer, InputMediaPoll

async def publish_quiz(client,chat,question,options,correct_index=None):
    answers=[PollAnswer(text=o.encode() if isinstance(o,str) else o, option=bytes([i]))
             for i,o in enumerate(options)]
    # Telethon raw poll construction varies by version; keep publishing isolated so it can be adapted.
    raise NotImplementedError("Native quiz publishing adapter is version-specific; use a tested Telethon version before enabling.")
