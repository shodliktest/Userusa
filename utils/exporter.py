import json
import re
from pathlib import Path
from typing import Any


def _plain(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    text = getattr(value, 'text', None)
    if text is not None and text is not value:
        return _plain(text)
    return str(value)


def _repair(value: str) -> str:
    s = _plain(value)
    markers = ('Ã', 'Â', 'â', 'ð', '�')
    if not any(m in s for m in markers):
        return s
    for enc in ('cp1252', 'latin1'):
        try:
            candidate = s.encode(enc).decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if sum(candidate.count(m) for m in markers) < sum(s.count(m) for m in markers):
            return candidate
    return s


def text(value: Any) -> str:
    s = _repair(value)
    s = s.replace('\u00a0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\r\n?', '\n', s)
    return s.strip()


def safe(s):
    return re.sub(r'[\\/:*?"<>|]+', ' ', text(s)).strip()[:90] or 'test'


def _options(q):
    raw = q.get('options_json')
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return []
    return q.get('options') or []


def export(quizzes, n=20, name='quiz_test'):
    out = []
    if not quizzes:
        return out
    n = max(1, int(n))
    for k in range(0, len(quizzes), n):
        batch = quizzes[k:k+n]
        base = name.strip() if name and name.strip() and name.strip().lower() != 'quiz_test' else text(batch[0].get('question', 'quiz_test'))[:70]
        lines = []
        for i, q in enumerate(batch, 1):
            lines.append(f'{i}. {text(q.get("question", ""))}')
            options = _options(q)
            try:
                correct = int(q.get('correct_index'))
            except (TypeError, ValueError):
                correct = -1
            for j, option in enumerate(options):
                prefix = '*' if j == correct else ''
                lines.append(f'{prefix}{chr(65+j)}) {text(option)}')
            explanation = text(q.get('explanation', ''))
            if explanation:
                lines.append('Izoh: ' + explanation)
            lines.append('')
        p = Path('exports') / f'{safe(base)}_{k//n+1:02d}.txt'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8', newline='')
        out.append(p)
    return out
