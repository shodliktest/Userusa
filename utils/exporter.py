import json
import re
from pathlib import Path


def safe(s):
    return re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]+', ' ', str(s))).strip()[:90] or 'test'


def export(quizzes, n=20, name='test'):
    out = []
    if not quizzes:
        return out
    for k in range(0, len(quizzes), n):
        batch = quizzes[k:k+n]
        # If the default name is used, derive a useful topic-like filename from the first question.
        base = name
        if not name.strip() or name.strip().lower() == 'quiz_test':
            base = batch[0].get('question', 'quiz_test')[:70]
        lines = []
        for i, q in enumerate(batch, 1):
            lines.append(f"{i}. {q['question'].strip()}")
            options = json.loads(q['options_json']) if isinstance(q.get('options_json'), str) else q['options']
            for j, option in enumerate(options):
                lines.append(f"{'*' if j == int(q['correct_index']) else ''}{chr(65+j)}) {option.strip()}")
            if q.get('explanation') and str(q['explanation']).strip():
                lines.append('Izoh: ' + str(q['explanation']).strip())
            lines.append('')
        p = Path('exports') / f'{safe(base)}_{k//n+1:02d}.txt'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
        out.append(p)
    return out
