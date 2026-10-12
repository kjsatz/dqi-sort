"""Apply text fixes to abstracts (for talks whose card says the text is malformed).

    python -m dqi_sort.fixes apply DATA_DIR FIXES.csv [--by claude]

Used two ways: Claude's automatic repair step (--by claude) after the cards flag malformed text, and the
lead's own corrections (the default, --by lead). Claude's fixes are strictly mechanical (remove pasted-in
author blocks and labels, rejoin run-together words, complete a cut-off word, restore an exponent only where
the text leaves no doubt); a missing value is never invented, and such talks stay flagged for the lead.

FIXES.csv: talk_id, field (title, body or submitter_notes), old, new, note. `old` must occur exactly once in
that field of abstracts.jsonl; it is replaced by `new` (which may be empty, to delete pasted-in text).
The text as it was before any fix is kept in `raw`, and each fix is recorded in `text_fix` with its `by`,
so a re-run of intake keeps it. A fixed title is copied to talks.csv. Nothing is written if any fix fails.

Prints the IDs of the fixed talks: rebuild their cards (cards prepare --ids) and re-embed.
"""
import argparse, csv, json, os, sys

FIELDS = ('title', 'body', 'submitter_notes')


def apply(data_dir, fixes_path, by='lead'):
    with open(fixes_path, encoding='utf-8', newline='') as f:
        fixes = list(csv.DictReader(f))
    apath = os.path.join(data_dir, 'abstracts.jsonl')
    with open(apath, encoding='utf-8') as f:
        recs = [json.loads(l) for l in f if l.strip()]
    by_id = {r['talk_id']: r for r in recs}
    errs, done = [], []
    for k, fx in enumerate(fixes, 2):
        i, field, old, new = fx['talk_id'].strip(), fx['field'].strip(), fx['old'], fx['new']
        r = by_id.get(i)
        if r is None or field not in FIELDS:
            errs.append(f'line {k}: unknown talk {i!r} or field {field!r}')
            continue
        n = (r[field] or '').count(old) if old else 0
        if n != 1:
            errs.append(f'line {k}: {i} {field}: the old text occurs {n} times (must be exactly once): {old[:60]!r}')
            continue
        r.setdefault('raw', {}).setdefault(field, r[field])
        r[field] = r[field].replace(old, new).strip()
        r.setdefault('text_fix', []).append({'field': field, 'fix': fx.get('note', '').strip() or 'text fix', 'by': by})
        done.append((i, field))
    if errs:
        for e in errs:
            print('ERROR', e)
        sys.exit(f'{len(errs)} fixes failed; nothing written')
    with open(apath, 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    titled = {i for i, field in done if field == 'title'}
    if titled:
        tpath = os.path.join(data_dir, 'talks.csv')
        with open(tpath, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        for t in rows:
            if t['talk_id'] in titled:
                t['title'] = by_id[t['talk_id']]['title']
        with open(tpath, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, list(rows[0].keys()), lineterminator='\n')
            w.writeheader(); w.writerows(rows)
    ids = sorted({i for i, _ in done}, key=lambda i: (len(i), i))
    print(f'applied {len(done)} fixes to {len(ids)} talks; rebuild their cards:')
    print('\n'.join(ids))
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['apply'])
    ap.add_argument('data_dir'); ap.add_argument('fixes'); ap.add_argument('--by', default='lead', choices=['lead', 'claude'])
    a = ap.parse_args()
    apply(a.data_dir, a.fixes, a.by)


if __name__ == '__main__':
    main()
