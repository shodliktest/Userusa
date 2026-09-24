import asyncio
import hashlib
import json
import re

from telethon import functions, errors
from ai.operator import Operator

URL = re.compile(r'(?:https?://|t\.me/|telegram\.me/)[^\s]+|(?<!\w)@[A-Za-z0-9_]{3,}', re.I)


def clean(s):
    s = URL.sub('', str(s or ''))
    s = re.sub(r'\s+', ' ', s)
    return s.strip(' -|•\t')


def fingerprint(q, options):
    data = {'q': clean(q).lower(), 'o': [clean(x).lower() for x in options]}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _text(v):
    if v is None:
        return ''
    return getattr(v, 'text', str(v)) or ''


def poll_from_message(msg):
    # Telethon exposes polls through Message.media.poll; Message.poll may also exist
    # depending on version. Prefer the raw media object for predictable behavior.
    media = getattr(msg, 'media', None)
    p = getattr(media, 'poll', None) if media else None
    if p is None:
        p = getattr(msg, 'poll', None)
    return p


def pdata(msg):
    p = poll_from_message(msg)
    if p is None or not bool(getattr(p, 'quiz', False)):
        return None
    q = clean(_text(getattr(p, 'question', '')))
    options = [clean(_text(a)) for a in (getattr(p, 'answers', None) or [])]
    options = [x for x in options if x]
    if not q or len(options) < 2:
        return None
    return q, options, p


async def native_correct_index(client, src, msg, poll):
    # First inspect already available poll results.
    results = getattr(poll, 'results', None)
    items = list(getattr(results, 'results', None) or [])
    for idx, item in enumerate(items):
        if bool(getattr(item, 'correct', False)):
            return idx

    # Refresh results. This does not magically reveal an answer when Telegram
    # does not expose it for that poll, but it catches polls whose correct flag
    # is available in the returned results.
    try:
        peer = await client.get_input_entity(src)
        fresh = await client(functions.messages.GetPollResults(
            peer=peer, msg_id=msg.id, poll_id=getattr(poll, 'id', 0),
            # Telethon versions differ in whether poll_hash is accepted. Do not
            # depend on it for the first pass.
        ))
        fresh_items = list(getattr(getattr(fresh, 'results', None), 'results', None) or [])
        for idx, item in enumerate(fresh_items):
            if bool(getattr(item, 'correct', False)):
                return idx
    except TypeError:
        try:
            peer = await client.get_input_entity(src)
            fresh = await client(functions.messages.GetPollResults(
                peer=peer, msg_id=msg.id, poll_hash=getattr(poll, 'hash', 0)
            ))
            fresh_items = list(getattr(getattr(fresh, 'results', None), 'results', None) or [])
            for idx, item in enumerate(fresh_items):
                if bool(getattr(item, 'correct', False)):
                    return idx
        except Exception:
            pass
    except Exception:
        pass
    return None


async def scan(client, db, src, target, stop_event, settings, stats, output_chat='', publish_enabled=False):
    operator = Operator()
    found = 0
    checked = 0
    skipped = 0
    published = 0
    state = db.state(src)
    last_id = int(state.get('last_message_id') or 0)
    stats.update(status='starting', source=str(src), found=0, checked=0, skipped=0, published=0, error='')

    try:
        async for msg in client.iter_messages(src, limit=None):
            if stop_event.is_set():
                stats['status'] = 'stopping'
                break
            if not getattr(msg, 'id', None):
                continue

            checked += 1
            stats.update(status='scanning', source=str(src), found=found, checked=checked, skipped=skipped, published=published)
            db.save_state(src, last_message_id=msg.id, checked=state.get('checked', 0) + checked, found=state.get('found', 0) + found)

            data = pdata(msg)
            if not data:
                continue
            q, options, poll = data
            fp = fingerprint(q, options)
            if db.fp(fp):
                skipped += 1
                continue

            correct = await native_correct_index(client, src, msg, poll)
            confidence = 1.0 if correct is not None else 0.0
            explanation = ''
            if correct is None and settings.quiz_ai_fallback:
                try:
                    correct, confidence, explanation = operator.solve(q, options)
                except Exception as exc:
                    db.log('ERROR', f'AI solve: {exc}')
                    correct = None

            if correct is None or not (0 <= int(correct) < len(options)) or confidence < settings.quiz_ai_min_confidence:
                skipped += 1
                db.log('WARN', f'Quiz skipped: confidence={confidence:.2f}; {q[:100]}')
                continue

            record = {
                'fingerprint': fp, 'source': str(src), 'message_id': msg.id,
                'question': q, 'options': options, 'correct_index': int(correct),
                'confidence': float(confidence), 'explanation': explanation,
            }
            db.savefp(fp, src, msg.id)
            db.save(record)
            found += 1

            if publish_enabled and output_chat:
                try:
                    from userbot.publisher import publish_quiz
                    await publish_quiz(client, output_chat, q, options, int(correct), explanation)
                    published += 1
                    db.log('INFO', f'Published quiz to {output_chat}: {q[:80]}')
                except Exception as exc:
                    db.log('ERROR', f'Publish failed for {q[:80]}: {exc}')

            stats.update(found=found, checked=checked, skipped=skipped, published=published)
            db.save_state(src, last_message_id=msg.id, checked=state.get('checked', 0) + checked, found=state.get('found', 0) + found)

            if target and found >= int(target):
                break
            await asyncio.sleep(0.8)
    except errors.FloodWaitError as exc:
        wait = int(getattr(exc, 'seconds', 0))
        stats.update(status='flood_wait', wait_seconds=wait)
        db.log('WARN', f'Telegram FloodWait: {wait}s for {src}')
        # Do not try to bypass Telegram limits. Leave the scanner stopped so the
        # operator can restart it after the server-imposed wait.
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
