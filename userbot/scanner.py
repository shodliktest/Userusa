import asyncio
import hashlib
import json
import re
from typing import Any

from telethon import errors, types
from telethon.tl.functions.messages import GetPollResultsRequest, SendVoteRequest

from utils.rate_limiter import GLOBAL_RATE_LIMITER, VOTE_RATE_LIMITER

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
    """Extract the real Telegram Poll from normal, forwarded or refreshed messages.

    Telegram/Telethon may expose a poll as Message.media.poll, msg.poll, or a
    nested TL wrapper. We only unwrap known poll-bearing fields and recursively
    inspect them. This is intentionally tolerant because forwarded polls are
    the main private-chat intake use case.
    """
    if msg is None:
        return None

    seen = set()

    def walk(obj, depth=0):
        if obj is None or depth > 8:
            return None
        oid = id(obj)
        if oid in seen:
            return None
        seen.add(oid)

        if isinstance(obj, types.Poll):
            return obj

        # Most common path: Message -> MessageMediaPoll -> Poll.
        for attr in ('poll', 'media', 'message', 'reply_to', 'fwd_from'):
            try:
                child = getattr(obj, attr, None)
            except Exception:
                child = None
            if child is None or child is obj:
                continue
            found = walk(child, depth + 1)
            if found is not None:
                return found

        if isinstance(obj, (list, tuple)):
            for child in obj:
                found = walk(child, depth + 1)
                if found is not None:
                    return found
        return None

    return walk(msg)


def forwarded_origin(msg):
    """Return (original_peer, original_message_id) when Telegram exposes it.

    For a true forward from a channel, MessageFwdHeader normally carries
    ``from_id=PeerChannel`` and ``channel_post``. This lets the intake try the
    original poll if voting the private-chat copy is rejected by Telegram.
    """
    if msg is None:
        return None, None
    fwd = getattr(msg, 'fwd_from', None)
    if fwd is None:
        # Telethon also exposes a higher-level ``forward`` object on Message.
        fwd = getattr(msg, 'forward', None)
    if fwd is None:
        return None, None

    peer = getattr(fwd, 'from_id', None) or getattr(fwd, 'saved_from_peer', None)
    msg_id = getattr(fwd, 'channel_post', None)
    if msg_id is None:
        msg_id = getattr(fwd, 'saved_from_msg_id', None)
    if peer is None or not msg_id:
        return None, None
    return peer, int(msg_id)


def is_poll_message(msg):
    """Cheap poll-media detector used before an exact-message refresh."""
    if msg is None:
        return False
    if poll_from_message(msg) is not None:
        return True
    media = getattr(msg, 'media', None)
    name = media.__class__.__name__.lower() if media is not None else ''
    return 'poll' in name

def pdata(msg, anonymous_only=True):
    poll = poll_from_message(msg)
    if poll is None or not bool(getattr(poll, 'quiz', False)):
        return None

    # Anonymous Telegram quiz = public_voters flag is absent/False.
    if anonymous_only and bool(getattr(poll, 'public_voters', False)):
        return None

    q = clean(getattr(poll, 'question', None))
    answers = list(getattr(poll, 'answers', None) or [])
    options = [clean(getattr(a, 'text', None)) for a in answers]
    if not q or len(options) < 2 or any(not x for x in options):
        return None
    return q, options, poll, answers


def poll_kind(msg):
    """Diagnostic classification used by scanner logs."""
    poll = poll_from_message(msg)
    if poll is None:
        return 'none'
    if not bool(getattr(poll, 'quiz', False)):
        return 'regular_poll'
    if bool(getattr(poll, 'public_voters', False)):
        return 'nonanonymous_quiz'
    return 'anonymous_quiz'


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
    return await GLOBAL_RATE_LIMITER.call(
        lambda: client(GetPollResultsRequest(
            peer=peer, msg_id=int(msg.id), poll_hash=poll_hash
        )),
        key="global",
        retries=4,
    )


async def telegram_correct_index(client, src, msg, poll, answers):
    """Read the correct answer from Telegram only, including true forwards.

    A forwarded poll can have two useful addressing modes:
      1) the message copy in the user's private chat;
      2) the original channel/group peer + original message ID from fwd_from.

    We try the exact private message first. If Telegram refuses/does not expose
    the result, we resolve the original forward header and try the original poll.
    No AI inference is ever used.
    """
    targets = []

    async def add_target(peer_like, msg_id, label):
        if peer_like is None or not msg_id:
            return
        try:
            peer = await client.get_input_entity(peer_like)
        except Exception as exc:
            # A raw PeerChannel from a forward may not be in the entity cache.
            # Keep the failure diagnostic but do not abort the private intake.
            return
        key = (repr(peer), int(msg_id))
        if not any(t[0] == key for t in targets):
            targets.append((key, peer, int(msg_id), label))

    await add_target(src, int(msg.id), 'private_message')
    fwd_peer, fwd_msg_id = forwarded_origin(msg)
    if fwd_peer is not None and fwd_msg_id:
        await add_target(fwd_peer, fwd_msg_id, 'forward_original')

    if not targets:
        raise ValueError(f'Poll uchun Telegram peer aniqlanmadi; msg_id={msg.id}')

    last_reason = 'Telegram result not exposed yet'

    for _, peer, target_msg_id, label in targets:
        # Refresh the exact target before voting. For an original forward this
        # also gives us the canonical poll/answer option IDs.
        current_msg = None
        current_poll = poll if target_msg_id == int(msg.id) and label == 'private_message' else None
        current_answers = list(answers or [])
        try:
            current_msg = await GLOBAL_RATE_LIMITER.call(
                lambda p=peer, mid=target_msg_id: client.get_messages(p, ids=mid),
                key='global', retries=4,
            )
            refreshed = poll_from_message(current_msg)
            if refreshed is not None:
                current_poll = refreshed
                refreshed_answers = list(getattr(refreshed, 'answers', None) or [])
                if len(refreshed_answers) >= 2:
                    current_answers = refreshed_answers
        except errors.RPCError as exc:
            last_reason = f'{label}: refresh {type(exc).__name__}: {exc}'

        if current_poll is None or len(current_answers) < 2:
            continue
        if not bool(getattr(current_poll, 'quiz', False)):
            continue

        # If Telegram already exposes a correct flag, no vote is needed.
        idx, solution = _correct_from_results(getattr(current_poll, 'results', None), current_answers)
        if idx is not None:
            return idx, solution, False

        vote_option = getattr(current_answers[0], 'option', None)
        if not isinstance(vote_option, (bytes, bytearray)):
            last_reason = f'{label}: option ID missing'
            continue

        response = None
        voted_now = False
        already_voted = False
        try:
            response = await VOTE_RATE_LIMITER.call(
                lambda p=peer, mid=target_msg_id, opt=bytes(vote_option): client(
                    SendVoteRequest(peer=p, msg_id=mid, options=[opt])
                ),
                key='vote', retries=10,
            )
            voted_now = True
        except errors.RPCError as exc:
            name = exc.__class__.__name__
            text = str(exc)
            if name == 'RevoteNotAllowedError' or 'REVOTE_NOT_ALLOWED' in text:
                already_voted = True
            elif name in ('FloodWaitError',):
                raise
            else:
                last_reason = f'{label}: {name}: {text}'
                # A true forward may be vote-restricted in the private copy but
                # still voteable at the original channel. Try the next target.
                continue

        # sendVote's Updates should contain updateMessagePoll with correct=True.
        results = _walk_poll_results(response)
        idx, solution = _correct_from_results(results, current_answers)
        if idx is not None:
            return idx, solution, voted_now

        # Refresh exact target after voting/already-voted state.
        try:
            refreshed_msg = await GLOBAL_RATE_LIMITER.call(
                lambda p=peer, mid=target_msg_id: client.get_messages(p, ids=mid),
                key='global', retries=4,
            )
            refreshed_poll = poll_from_message(refreshed_msg)
            if refreshed_poll is not None:
                refreshed_answers2 = list(getattr(refreshed_poll, 'answers', None) or []) or current_answers
                idx, solution = _correct_from_results(
                    getattr(refreshed_poll, 'results', None), refreshed_answers2
                )
                if idx is not None:
                    return idx, solution, voted_now
                current_poll = refreshed_poll
                current_answers = refreshed_answers2
        except errors.RPCError as exc:
            last_reason = f'{label}: post-vote refresh {type(exc).__name__}: {exc}'

        # Poll hash endpoint is the authoritative fallback documented by Telegram.
        poll_hash = int(getattr(current_poll, 'hash', 0) or 0)
        if poll_hash:
            try:
                fresh = await GLOBAL_RATE_LIMITER.call(
                    lambda p=peer, mid=target_msg_id, ph=poll_hash: client(
                        GetPollResultsRequest(peer=p, msg_id=mid, poll_hash=ph)
                    ),
                    key='global', retries=4,
                )
                idx, solution = _correct_from_results(
                    _walk_poll_results(fresh) or fresh, current_answers
                )
                if idx is not None:
                    return idx, solution, voted_now
            except errors.RPCError as exc:
                last_reason = f'{label}: getPollResults {type(exc).__name__}: {exc}'

        last_reason = f'{label}: ' + ('already voted; result unavailable' if already_voted else 'vote sent but result unavailable')

    raise ValueError(f'Telegram quiz correct answer unavailable; {last_reason}; private_msg_id={msg.id}')


def _is_single_image_message(msg):
    if msg is None:
        return False
    grouped = getattr(msg, 'grouped_id', None)
    if grouped is not None:
        return False
    if getattr(msg, 'photo', None) is not None:
        return True
    doc = getattr(msg, 'document', None)
    if doc is not None and str(getattr(doc, 'mime_type', '') or '').lower().startswith('image/'):
        return True
    media = getattr(msg, 'media', None)
    name = media.__class__.__name__.lower() if media is not None else ''
    return 'photo' in name and 'document' not in name


async def _find_adjacent_image(client, src, quiz_msg):
    """Find only the immediately preceding single image (message_id - 1)."""
    mid = int(getattr(quiz_msg, 'id', 0) or 0)
    if mid <= 1:
        return ''
    try:
        prev = await GLOBAL_RATE_LIMITER.call(
            lambda: client.get_messages(src, ids=mid - 1),
            key='global', retries=4,
        )
    except errors.RPCError:
        return ''
    if not _is_single_image_message(prev):
        return ''

    root = Path('data') / 'scanner_images'
    root.mkdir(parents=True, exist_ok=True)
    source_key = hashlib.sha1(str(src).encode('utf-8')).hexdigest()[:16]
    folder = root / source_key
    folder.mkdir(parents=True, exist_ok=True)
    suffix = '.jpg' if getattr(prev, 'photo', None) is not None else '.img'
    path = folder / f'{int(prev.id)}{suffix}'
    if path.is_file() and path.stat().st_size > 0:
        return str(path)
    try:
        downloaded = await client.download_media(prev, file=str(path))
        return str(downloaded) if downloaded else ''
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return ''


async def _send_docx_batch(client, output_chat, records):
    if not records or not output_chat:
        return None
    from utils.exporter import export
    files = export(records, len(records), 'quiz_test')
    sent = 0
    try:
        for path in files:
            await client.send_file(
                await client.get_input_entity(output_chat),
                str(path),
                caption=f'Quizlar: {len(records)} ta\nManba: {records[0].get("source", "")}',
            )
            sent += 1
    finally:
        for path in files:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
    return sent


async def scan(client, db, src, target, stop_event, settings, stats, output_chat='',
               publish_enabled=False, file_publish_enabled=True, per_file=20,
               scan_mode='target'):
    found = checked = skipped = published = files_sent = 0
    polls_seen = anonymous_quizzes = answer_failures = duplicate_count = 0
    flood_waits_start = GLOBAL_RATE_LIMITER.flood_waits
    flood_wait_seconds_start = GLOBAL_RATE_LIMITER.flood_wait_seconds
    vote_flood_waits_start = VOTE_RATE_LIMITER.flood_waits
    vote_flood_wait_seconds_start = VOTE_RATE_LIMITER.flood_wait_seconds
    batch_records = []
    state = db.state(src)

    full_history = str(scan_mode or 'target').lower() in ('full', 'all', 'history')
    state_last = int(state.get('last_message_id', 0) or 0)
    mode_name = 'FULL_HISTORY' if full_history else 'TARGET'
    stats.update(status='starting', source=str(src), found=0, checked=0, skipped=0,
                 published=0, files_sent=0, polls_seen=0, anonymous_quizzes=0,
                 answer_failures=0, duplicates=0, error='')
    db.log('INFO', f'Scan MODE={mode_name}: {src}; target={target}; checkpoint={state_last}')

    try:
        # Telethon documents reverse=True as oldest -> newest. When resuming a
        # full-history scan, min_id excludes everything already checkpointed.
        if full_history:
            if state_last > 0:
                iterator = client.iter_messages(src, limit=None, reverse=True, min_id=state_last)
            else:
                iterator = client.iter_messages(src, limit=None, reverse=True)
        else:
            iterator = client.iter_messages(src, limit=None)

        checkpoint_every = 25
        since_checkpoint = 0
        last_seen_id = state_last

        async for msg in iterator:
            if stop_event.is_set():
                stats['status'] = 'stopping'
                break
            mid = int(getattr(msg, 'id', 0) or 0)
            if mid <= 0:
                continue
            if full_history and state_last and mid <= state_last:
                continue

            checked += 1
            last_seen_id = mid
            since_checkpoint += 1

            kind = poll_kind(msg)
            if kind != 'none':
                polls_seen += 1
            if kind == 'anonymous_quiz':
                anonymous_quizzes += 1

            stats.update(status='scanning', source=str(src), found=found, checked=checked,
                         skipped=skipped, published=published, files_sent=files_sent,
                         polls_seen=polls_seen, anonymous_quizzes=anonymous_quizzes,
                         answer_failures=answer_failures, duplicates=duplicate_count,
                         flood_waits=GLOBAL_RATE_LIMITER.flood_waits - flood_waits_start,
                         flood_wait_seconds=(GLOBAL_RATE_LIMITER.flood_wait_seconds - flood_wait_seconds_start) + (VOTE_RATE_LIMITER.flood_wait_seconds - vote_flood_wait_seconds_start),
                     vote_flood_waits=VOTE_RATE_LIMITER.flood_waits - vote_flood_waits_start)

            correct = None
            data = pdata(msg, anonymous_only=True)
            if not data:
                # Persist progress in full-history mode even across non-quiz runs.
                if full_history and since_checkpoint >= checkpoint_every:
                    db.save_state(src, last_message_id=last_seen_id)
                    since_checkpoint = 0
                continue

            q, options, poll, answers = data
            fp = fingerprint(q, options)
            if db.fp(fp):
                skipped += 1
                duplicate_count += 1
                db.log('INFO', f'SKIP duplicate fingerprint: {src}:{mid}; {q[:80]}')
            else:
                try:
                    correct, solution, voted_now = await telegram_correct_index(
                        client, src, msg, poll, answers
                    )
                except errors.RPCError as exc:
                    skipped += 1
                    answer_failures += 1
                    db.log('WARN', f'Answer RPC failed: {type(exc).__name__}: {exc}; msg_id={mid}; {q[:100]}')
                    correct = None
                except Exception as exc:
                    skipped += 1
                    answer_failures += 1
                    db.log('WARN', f'Answer extraction failed: {type(exc).__name__}: {exc}; msg_id={mid}; {q[:100]}')
                    correct = None

                if correct is not None:
                    image_path = ''
                    try:
                        # Exact rule requested: only the single image immediately
                        # before this quiz (message_id - 1) is attached.
                        image_path = await _find_adjacent_image(client, src, msg)
                    except Exception as exc:
                        db.log('WARN', f'Image pairing failed {src}:{mid}: {type(exc).__name__}: {exc}')

                    record = {
                        'fingerprint': fp,
                        'source': str(src),
                        'message_id': mid,
                        'question': q,
                        'options': options,
                        'correct_index': int(correct),
                        'confidence': 1.0,
                        'explanation': clean(solution),
                        'answer_source': 'telegram_poll_results',
                        'voted_now': bool(voted_now),
                        'image_path': image_path,
                    }
                    db.savefp(fp, src, mid)
                    db.save(record)
                    found += 1
                    batch_records.append(record)
                    db.log('INFO', f'QUIZ OK {src}:{mid}: {q[:100]}')

                    if publish_enabled and output_chat:
                        try:
                            from userbot.publisher import publish_quiz
                            await publish_quiz(client, output_chat, q, options, int(correct), clean(solution))
                            published += 1
                        except Exception as exc:
                            db.log('ERROR', f'Publish failed for {q[:80]}: {type(exc).__name__}: {exc}')

                    if file_publish_enabled and output_chat and len(batch_records) >= max(1, int(per_file)):
                        try:
                            sent = await _send_docx_batch(client, output_chat, batch_records)
                            files_sent += int(sent or 0)
                            db.log('INFO', f'DOCX yuborildi: {output_chat}; {len(batch_records)} quiz; files={sent or 0}')
                            batch_records.clear()
                        except Exception as exc:
                            db.log('ERROR', f'DOCX yuborish xatosi {output_chat}: {type(exc).__name__}: {exc}')

            # Checkpoint every N messages, and always on every successful quiz.
            if full_history and (since_checkpoint >= checkpoint_every or correct is not None):
                db.save_state(src, last_message_id=last_seen_id,
                              checked=state.get('checked', 0) + checked,
                              found=state.get('found', 0) + found)
                since_checkpoint = 0

            stats.update(found=found, checked=checked, skipped=skipped,
                         published=published, files_sent=files_sent,
                         polls_seen=polls_seen, anonymous_quizzes=anonymous_quizzes,
                         answer_failures=answer_failures, duplicates=duplicate_count,
                         flood_waits=GLOBAL_RATE_LIMITER.flood_waits - flood_waits_start,
                         flood_wait_seconds=(GLOBAL_RATE_LIMITER.flood_wait_seconds - flood_wait_seconds_start) + (VOTE_RATE_LIMITER.flood_wait_seconds - vote_flood_wait_seconds_start),
                     vote_flood_waits=VOTE_RATE_LIMITER.flood_waits - vote_flood_waits_start)

            if (not full_history) and target and found >= int(target):
                db.log('INFO', f'Target reached: {found}/{target}')
                break

            await asyncio.sleep(0.35)

        if full_history and last_seen_id > 0:
            db.save_state(src, last_message_id=last_seen_id,
                          checked=state.get('checked', 0) + checked,
                          found=state.get('found', 0) + found)

        if batch_records and file_publish_enabled and output_chat:
            try:
                sent = await _send_docx_batch(client, output_chat, batch_records)
                files_sent += int(sent or 0)
                db.log('INFO', f'DOCX yuborildi: {output_chat}; {len(batch_records)} quiz; files={sent or 0}')
                batch_records.clear()
            except Exception as exc:
                db.log('ERROR', f'DOCX yuborish xatosi {output_chat}: {type(exc).__name__}: {exc}')

        db.log('INFO', f'SCAN SUMMARY {src}: checked={checked}, polls={polls_seen}, anonymous_quizzes={anonymous_quizzes}, found={found}, duplicates={duplicate_count}, answer_failures={answer_failures}, flood_waits={GLOBAL_RATE_LIMITER.flood_waits - flood_waits_start}, flood_wait_seconds={(GLOBAL_RATE_LIMITER.flood_wait_seconds - flood_wait_seconds_start) + (VOTE_RATE_LIMITER.flood_wait_seconds - vote_flood_wait_seconds_start)}, vote_flood_waits={VOTE_RATE_LIMITER.flood_waits - vote_flood_waits_start}')

    except errors.FloodWaitError as exc:
        wait = int(getattr(exc, 'seconds', 0))
        stats.update(status='flood_wait', wait_seconds=wait)
        db.log('WARN', f'Telegram FloodWait: {wait}s for {src}')
    except Exception as exc:
        stats.update(status='error', error=str(exc))
        db.log('ERROR', f'Scanner {src}: {type(exc).__name__}: {exc}')
        raise
    finally:
        if stop_event.is_set() and stats.get('status') != 'error':
            stats['status'] = 'stopped'
        elif stats.get('status') not in ('error', 'flood_wait'):
            stats['status'] = 'completed'
        stats.update(found=found, checked=checked, skipped=skipped, published=published,
                     files_sent=files_sent, polls_seen=polls_seen,
                     anonymous_quizzes=anonymous_quizzes, answer_failures=answer_failures,
                     duplicates=duplicate_count,
                     flood_waits=GLOBAL_RATE_LIMITER.flood_waits - flood_waits_start,
                     flood_wait_seconds=(GLOBAL_RATE_LIMITER.flood_wait_seconds - flood_wait_seconds_start) + (VOTE_RATE_LIMITER.flood_wait_seconds - vote_flood_wait_seconds_start),
                     vote_flood_waits=VOTE_RATE_LIMITER.flood_waits - vote_flood_waits_start)
    return found

