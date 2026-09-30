import asyncio
import hashlib
import json
import re
from typing import Any

from telethon import errors, types
from telethon.tl.functions.messages import GetPollResultsRequest, SendVoteRequest

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
    """Return the real TL Poll from normal, forwarded and shared messages.

    Telethon normally exposes it as Message.media.poll, but forwarded/shared
    messages can be wrapped more deeply. We deliberately unwrap only known
    poll-bearing TL fields and never treat arbitrary message text as a poll.
    """
    if msg is None:
        return None

    seen = set()

    def walk(obj, depth=0):
        if obj is None or depth > 5:
            return None
        oid = id(obj)
        if oid in seen:
            return None
        seen.add(oid)

        # The actual Telegram Poll constructor.
        if isinstance(obj, types.Poll):
            return obj

        # Standard Message -> MessageMediaPoll -> Poll.
        poll = getattr(obj, 'poll', None)
        if isinstance(poll, types.Poll):
            return poll

        # Unwrap common TL containers used by MessageMediaPoll / forwarded data.
        for attr in ('media', 'message', 'reply_to', 'fwd_from'):
            child = getattr(obj, attr, None)
            if child is not None:
                found = walk(child, depth + 1)
                if found is not None:
                    return found

        # Some Telethon containers expose nested lists.
        if isinstance(obj, (list, tuple)):
            for child in obj:
                found = walk(child, depth + 1)
                if found is not None:
                    return found
        return None

    return walk(msg)


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
    return await client(GetPollResultsRequest(
        peer=peer, msg_id=int(msg.id), poll_hash=poll_hash
    ))


async def telegram_correct_index(client, src, msg, poll, answers):
    """Read the correct answer from Telegram's anonymous quiz result; never use AI.

    Workflow:
      1) Work with the exact source peer + quiz message ID.
      2) If Telegram already exposed a correct flag locally, use it.
      3) Otherwise cast ONE vote on the first option. The MTProto response contains
         PollResults with ``correct=True`` on the correct answer(s).
      4) If voting is refused because this account already voted, refresh the SAME
         message and fetch its current poll results.
      5) Never infer/guess the answer and never call Groq/Gemini here.
    """
    peer = await client.get_input_entity(src)

    # 1. Current message state may already contain the answer.
    idx, solution = _correct_from_results(getattr(poll, 'results', None), answers)
    if idx is not None:
        return idx, solution, False

    vote_option = getattr(answers[0], 'option', None)
    if not isinstance(vote_option, (bytes, bytearray)):
        raise ValueError('Telegram quiz option ID topilmadi')

    response = None
    voted_now = False
    already_voted = False
    try:
        response = await client(SendVoteRequest(
            peer=peer,
            msg_id=int(msg.id),
            options=[bytes(vote_option)],
        ))
        voted_now = True
    except errors.RPCError as exc:
        name = exc.__class__.__name__
        if name == 'RevoteNotAllowedError' or 'REVOTE_NOT_ALLOWED' in str(exc):
            already_voted = True
        else:
            raise

    # 2. Best/authoritative path: inspect the exact sendVote update.
    results = _walk_poll_results(response)
    idx, solution = _correct_from_results(results, answers)
    if idx is not None:
        return idx, solution, voted_now

    # 3. Refresh the exact message ID. This is important when the account voted
    # earlier or when Telethon's update object does not contain the full result.
    refreshed_poll = None
    try:
        refreshed_msg = await client.get_messages(peer, ids=int(msg.id))
        refreshed_poll = poll_from_message(refreshed_msg)
        if refreshed_poll is not None:
            idx, solution = _correct_from_results(
                getattr(refreshed_poll, 'results', None), answers
            )
            if idx is not None:
                return idx, solution, voted_now
    except errors.RPCError:
        pass

    # 4. Ask Telegram for the current results using the latest poll hash.
    # If the refreshed message is unavailable, use the original poll hash.
    poll_for_hash = refreshed_poll or poll
    poll_hash = int(getattr(poll_for_hash, 'hash', 0) or 0)
    if poll_hash:
        try:
            fresh = await client(GetPollResultsRequest(
                peer=peer,
                msg_id=int(msg.id),
                poll_hash=poll_hash,
            ))
            idx, solution = _correct_from_results(
                _walk_poll_results(fresh) or fresh, answers
            )
            if idx is not None:
                return idx, solution, voted_now
        except errors.RPCError:
            pass

    # 5. One final exact-message refresh. Do not scan another message and do not
    # ask an AI model to infer the answer.
    try:
        refreshed_msg = await client.get_messages(peer, ids=int(msg.id))
        refreshed_poll = poll_from_message(refreshed_msg)
        if refreshed_poll is not None:
            idx, solution = _correct_from_results(
                getattr(refreshed_poll, 'results', None), answers
            )
            if idx is not None:
                return idx, solution, voted_now
    except errors.RPCError:
        pass

    reason = 'already voted' if already_voted else 'Telegram result not exposed yet'
    raise ValueError(f'Telegram anonymous quiz correct answer unavailable: {reason}; msg_id={msg.id}')


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
                         answer_failures=answer_failures, duplicates=duplicate_count)

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
                         answer_failures=answer_failures, duplicates=duplicate_count)

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

        db.log('INFO', f'SCAN SUMMARY {src}: checked={checked}, polls={polls_seen}, anonymous_quizzes={anonymous_quizzes}, found={found}, duplicates={duplicate_count}, answer_failures={answer_failures}')

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
                     duplicates=duplicate_count)
    return found

