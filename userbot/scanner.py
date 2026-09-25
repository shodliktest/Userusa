import asyncio
import hashlib
import json
import re
from typing import Any

from telethon import functions, errors, types

URL = re.compile(r'(?:https?://|t\.me/|telegram\.me/)[^\s]+|(?<!\w)@[A-Za-z0-9_]{3,}', re.I)


def plain_text(value: Any) -> str:
    """Convert Telethon TextWithEntities / nested TL text objects to plain text."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    text = getattr(value, 'text', None)
    if text is not None and text is not value:
        return plain_text(text)
    return str(value)


def repair_mojibake(value: str) -> str:
    """Repair common UTF-8 decoded as cp1252/latin-1 corruption without touching normal text."""
    s = str(value or '')
    markers = ('Ã', 'Â', 'â', 'ð', '�')
    if not any(m in s for m in markers):
        return s
    try:
        candidate = s.encode('cp1252').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            candidate = s.encode('latin1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    bad_before = sum(s.count(m) for m in markers)
    bad_after = sum(candidate.count(m) for m in markers)
    return candidate if bad_after < bad_before else s


def clean(s: Any) -> str:
    s = repair_mojibake(plain_text(s))
    s = URL.sub('', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip(' -|•\t')


def fingerprint(q, options):
    data = {'q': clean(q).casefold(), 'o': [clean(x).casefold() for x in options]}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def poll_from_message(msg):
    media = getattr(msg, 'media', None)
    poll = getattr(media, 'poll', None) if media else None
    if poll is None:
        poll = getattr(msg, 'poll', None)
    return poll


def pdata(msg):
    poll = poll_from_message(msg)
    if poll is None or not bool(getattr(poll, 'quiz', False)):
        return None
    q = clean(getattr(poll, 'question', None))
    answers = list(getattr(poll, 'answers', None) or [])
    options = [clean(getattr(a, 'text', None)) for a in answers]
    if not q or len(options) < 2 or any(not x for x in options):
        return None
    return q, options, poll, answers


def _walk_poll_results(obj, seen=None):
    """Find PollResults anywhere inside a Telethon Updates object."""
    if obj is None:
        return None
    if seen is None:
        seen = set()
    oid = id(obj)
    if oid in seen:
        return None
    seen.add(oid)

    if isinstance(obj, (types.PollResults,)):
        return obj
    # updateMessagePoll has .results; nested Updates have .updates / .users / .chats.
    results = getattr(obj, 'results', None)
    if isinstance(results, types.PollResults):
        return results
    if results is not None:
        found = _walk_poll_results(results, seen)
        if found:
            return found

    if isinstance(obj, (list, tuple)):
        for item in obj:
            found = _walk_poll_results(item, seen)
            if found:
                return found
        return None

    for attr in ('updates', 'messages', 'users', 'chats'):
        child = getattr(obj, attr, None)
        if child is not None:
            found = _walk_poll_results(child, seen)
            if found:
                return found
    return None


def _correct_from_results(results, answers):
    if not results:
        return None, ''
    rows = list(getattr(results, 'results', None) or [])
    # The result vector follows poll.answers order. Match by option bytes when possible,
    # otherwise fall back to the positional order documented by Telegram.
    for idx, answer in enumerate(answers):
        option_id = getattr(answer, 'option', None)
        for row_idx, row in enumerate(rows):
            if option_id is not None and getattr(row, 'option', None) == option_id:
                if bool(getattr(row, 'correct', False)):
                    return idx, plain_text(getattr(results, 'solution', '') or '')
                break
        if idx < len(rows) and bool(getattr(rows[idx], 'correct', False)):
            return idx, plain_text(getattr(results, 'solution', '') or '')
    return None, plain_text(getattr(results, 'solution', '') or '')


async def _get_results(client, peer, msg, poll):
    poll_hash = int(getattr(poll, 'hash', 0) or 0)
    if not poll_hash:
        return None
    return await client(functions.messages.GetPollResults(
        peer=peer, msg_id=int(msg.id), poll_hash=poll_hash
    ))


async def telegram_correct_index(client, src, msg, poll, answers):
    """Obtain the quiz answer from Telegram itself; never solve the question with AI.

    We first use any correct flag already present. Otherwise we cast exactly one vote
    (the first option). Telegram's MTProto response to messages.sendVote contains
    PollResults where the correct option is marked with `correct=True`.
    If this account has already voted and revoting is disabled, we fetch the current
    poll results instead.
    """
    peer = await client.get_input_entity(src)

    # Existing local poll state may already contain the answer after a previous vote.
    idx, solution = _correct_from_results(getattr(poll, 'results', None), answers)
    if idx is not None:
        return idx, solution, False

    vote_option = getattr(answers[0], 'option', None)
    if not isinstance(vote_option, (bytes, bytearray)):
        raise ValueError('Telegram quiz option ID topilmadi')

    response = None
    voted_now = False
    try:
        response = await client(functions.messages.SendVote(
            peer=peer,
            msg_id=int(msg.id),
            options=[bytes(vote_option)],
        ))
        voted_now = True
    except errors.RPCError as exc:
        # Telethon error class names can vary slightly by generated layer/version.
        # Only REVOTE_NOT_ALLOWED means 'already voted'; all other RPC errors are real failures.
        if exc.__class__.__name__ == 'RevoteNotAllowedError' or 'REVOTE_NOT_ALLOWED' in str(exc):
            response = None
        else:
            raise

    results = _walk_poll_results(response)
    idx, solution = _correct_from_results(results, answers)
    if idx is not None:
        return idx, solution, voted_now

    # The sendVote response can be minimal; fetch the current state with poll.hash.
    try:
        fresh = await _get_results(client, peer, msg, poll)
        idx, solution = _correct_from_results(_walk_poll_results(fresh) or fresh, answers)
        if idx is not None:
            return idx, solution, voted_now
    except errors.RPCError:
        pass

    # Last local refresh: Telegram may have delivered the updated poll to the client.
    try:
        refreshed_msg = await client.get_messages(peer, ids=int(msg.id))
        refreshed_poll = poll_from_message(refreshed_msg)
        if refreshed_poll is not None:
            idx, solution = _correct_from_results(getattr(refreshed_poll, 'results', None), answers)
            if idx is not None:
                return idx, solution, voted_now
    except errors.RPCError:
        pass

    return None, solution, voted_now


async def scan(client, db, src, target, stop_event, settings, stats, output_chat='', publish_enabled=False):
    found = checked = skipped = published = 0
    state = db.state(src)
    stats.update(status='starting', source=str(src), found=0, checked=0, skipped=0, published=0, error='')

    try:
        # Start from newest messages. We keep a checkpoint so a later run can skip
        # already processed message IDs while still allowing new history to be seen.
        async for msg in client.iter_messages(src, limit=None):
            if stop_event.is_set():
                stats['status'] = 'stopping'
                break
            if not getattr(msg, 'id', None):
                continue

            checked += 1
            stats.update(status='scanning', source=str(src), found=found, checked=checked,
                         skipped=skipped, published=published)

            data = pdata(msg)
            if not data:
                continue
            q, options, poll, answers = data
            fp = fingerprint(q, options)
            if db.fp(fp):
                skipped += 1
                continue

            try:
                correct, solution, voted_now = await telegram_correct_index(
                    client, src, msg, poll, answers
                )
            except errors.RPCError as exc:
                skipped += 1
                db.log('WARN', f'Vote failed: {type(exc).__name__}: {exc}; msg_id={msg.id}; {q[:100]}')
                continue

            if correct is None:
                skipped += 1
                db.log('WARN', f'Telegram correct answer not exposed; msg_id={msg.id}; {q[:100]}')
                continue

            record = {
                'fingerprint': fp,
                'source': str(src),
                'message_id': int(msg.id),
                'question': q,
                'options': options,
                'correct_index': int(correct),
                'confidence': 1.0,
                'explanation': clean(solution),
                'answer_source': 'telegram_poll_results',
                'voted_now': bool(voted_now),
            }
            db.savefp(fp, src, msg.id)
            db.save(record)
            found += 1

            if publish_enabled and output_chat:
                try:
                    from userbot.publisher import publish_quiz
                    await publish_quiz(client, output_chat, q, options, int(correct), clean(solution))
                    published += 1
                    db.log('INFO', f'Published quiz to {output_chat}: {q[:80]}')
                except Exception as exc:
                    db.log('ERROR', f'Publish failed for {q[:80]}: {exc}')

            db.save_state(src, last_message_id=msg.id,
                          checked=state.get('checked', 0) + checked,
                          found=state.get('found', 0) + found)
            stats.update(found=found, checked=checked, skipped=skipped, published=published)

            if target and found >= int(target):
                break
            await asyncio.sleep(0.8)

    except errors.FloodWaitError as exc:
        wait = int(getattr(exc, 'seconds', 0))
        stats.update(status='flood_wait', wait_seconds=wait)
        db.log('WARN', f'Telegram FloodWait: {wait}s for {src}')
    except Exception as exc:
        stats.update(status='error', error=str(exc))
        db.log('ERROR', f'Scanner {src}: {exc}')
        raise
    finally:
        if stop_event.is_set() and stats.get('status') != 'error':
            stats['status'] = 'stopped'
        elif stats.get('status') not in ('error', 'flood_wait'):
            stats['status'] = 'completed'
        stats.update(found=found, checked=checked, skipped=skipped, published=published)
    return found
