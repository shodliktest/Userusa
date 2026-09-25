import random
from telethon import functions, types


async def publish_quiz(client, chat, q, options, correct, explanation=''):
    """Publish a real Telegram Quiz poll with Telegram's stored correct answer."""
    answers = [
        types.PollAnswer(
            text=types.TextWithEntities(text=str(x), entities=[]),
            option=bytes([i]),
        )
        for i, x in enumerate(options)
    ]
    poll = types.Poll(
        id=random.getrandbits(63),
        closed=False,
        public_voters=False,
        multiple_choice=False,
        quiz=True,
        question=types.TextWithEntities(text=str(q)[:300], entities=[]),
        answers=answers,
    )
    media = types.InputMediaPoll(
        poll=poll,
        correct_answers=[bytes([int(correct)])],
        solution=(str(explanation)[:200] if explanation else None),
    )
    peer = await client.get_input_entity(str(chat).strip())
    return await client(functions.messages.SendMediaRequest(
        peer=peer,
        media=media,
        message='',
        random_id=random.getrandbits(63),
    ))
