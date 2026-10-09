"""Stage 1: read the APS workbook export(s) into talks.csv and abstracts.jsonl.

    python -m dqi_sort.intake DATA_DIR [--dry-run]

Reads DATA_DIR/config.yaml:
    aps_input:    {in_person: {file: ..., sheet: ...}, virtual: {file: ...}}   (CSV or .xlsx; sheet only for .xlsx)
    aps_columns:  {APS header: field}, fields from FIELDS below
    aps_types:    {APS type: oral | invited}
    talk_lengths_min, dqi_categories (optional: flags talks submitted to other categories)

Writes, sorted by talk ID:
    talks.csv          intake columns updated; columns owned by later stages (institution, area, series,
                       status, notes, ...) kept for talks already there. Talks missing from the input are kept
                       and flagged, never deleted.
    abstracts.jsonl    text with minimal repairs (see textfix.py); `raw` holds each changed field as received,
                       `text_fix` says what changed. Records with a manual fix (by != intake) are kept as they are.
    reference/aps_assignments.csv
                       any session assignments already in the input (session, order, sorter note). Sorting never
                       reads this; only scoring does.
"""
import argparse, collections, csv, json, os, re, sys
import yaml
from dqi_sort import textfix

FIELDS = {'talk_id', 'first_name', 'last_name', 'speaker', 'affiliation', 'submitted_category', 'type', 'title',
          'body', 'submitter_notes', 'time_windows', 'session_id', 'order', 'sorter_note'}
REQUIRED = {'talk_id', 'type', 'title'}
TEXT_FIELDS = ['title', 'body', 'submitter_notes', 'affiliation', 'speaker']
TALK_COLS = ['talk_id', 'track', 'type', 'minutes', 'title', 'speaker', 'affiliation', 'institution',
             'submitted_category', 'area', 'series', 'series_part', 'time_windows', 'status', 'flags', 'notes']
INTAKE_COLS = ['track', 'type', 'minutes', 'title', 'speaker', 'affiliation', 'submitted_category', 'time_windows']
INTAKE_FLAGS = ('no_abstract', 'text_repaired', 'still_garbled', 'same_abstract', 'same_title',
                'category_not_dqi', 'no_time_window', 'not_in_aps_input')
REF_COLS = ['talk_id', 'session_id', 'order', 'locked', 'note']


def id_key(i):
    return (len(i), i)


# ---------- reading ----------
def read_table(path, sheet=None):
    """Return all rows as lists of strings (CSV, or one sheet of an .xlsx workbook)."""
    if path.lower().endswith('.xlsx'):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        rows = [['' if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        with open(path, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
    return rows


def find_header(rows, colmap):
    keys = {k for k, v in colmap.items() if v in REQUIRED}
    for n, r in enumerate(rows):
        if keys <= {c.strip() for c in r}:
            return n
    sys.exit(f'no header row with columns {sorted(keys)}')


def read_track(data_dir, track, spec, colmap):
    path = os.path.join(data_dir, spec['file'])
    rows = read_table(path, spec.get('sheet'))
    h = find_header(rows, colmap)
    header = [c.strip() for c in rows[h]]
    unknown = [c for k, c in enumerate(header) if c not in colmap and any(k < len(r) and r[k].strip() for r in rows[h + 1:])]
    if unknown:
        print(f'  {track}: ignoring unmapped columns with data: {unknown}')
    out = []
    for r in rows[h + 1:]:
        if not any(c.strip() for c in r):
            continue
        rec = {}
        for k, c in enumerate(header):
            if c in colmap and k < len(r):
                rec[colmap[c]] = r[k]
        rec['talk_id'] = rec.get('talk_id', '').strip()
        if not rec['talk_id']:
            continue
        rec['track'] = track
        out.append(rec)
    print(f'  {track}: {len(out)} talks from {spec["file"]}')
    return out


# ---------- per-talk processing ----------
_WINDOW = re.compile(r'(\d{1,2}):(\d\d)\s*([AP]M)\s*[-–]\s*(\d{1,2}):(\d\d)\s*([AP]M)\s*\(?([A-Z]{2,4})?\)?', re.I)

def _24h(h, m, ap):
    h = int(h) % 12 + (12 if ap.upper() == 'PM' else 0)
    return f'{h:02d}:{m}'

def normalize_windows(s):
    """'5:30 AM - 7:30 AM (MDT);10:30 AM - 12:30 PM (MDT)' -> '05:30-07:30 MDT;10:30-12:30 MDT'.
    Anything that does not parse is kept as given."""
    out = []
    for part in filter(None, (p.strip() for p in (s or '').split(';'))):
        m = _WINDOW.fullmatch(part)
        out.append(f'{_24h(*m.group(1, 2, 3))}-{_24h(*m.group(4, 5, 6))}' + (f' {m.group(7).upper()}' if m.group(7) else '')
                   if m else part)
    return ';'.join(out)


def process(rec, cfg):
    types = cfg.get('aps_types') or {'Oral': 'oral', 'Invited': 'invited'}
    raw_type = rec.get('type', '').strip()
    typ = types.get(raw_type)
    if typ is None:
        sys.exit(f"talk {rec['talk_id']}: unknown type {raw_type!r}; add it to aps_types in config.yaml")
    if 'speaker' not in rec:
        rec['speaker'] = f"{rec.get('first_name', '').strip()} {rec.get('last_name', '').strip()}".strip()
    text, raw, fixes, flags = {}, {}, [], []
    for f in TEXT_FIELDS:
        orig = rec.get(f, '') or ''
        new, what = textfix.clean(orig)
        text[f] = new
        if what:
            raw[f] = orig
            fixes += [{'field': f, 'fix': w, 'by': 'intake'} for w in what]
        if textfix.suspect(new):
            flags.append('still_garbled')
    if fixes:
        flags.append('text_repaired')
    if not text['body']:
        flags.append('no_abstract')
    cat = rec.get('submitted_category', '').strip()
    if cfg.get('dqi_categories') and cat not in cfg['dqi_categories']:
        flags.append('category_not_dqi')
    windows = normalize_windows(rec.get('time_windows', ''))
    if rec['track'] == 'virtual' and not windows:
        flags.append('no_time_window')
    talk = {'talk_id': rec['talk_id'], 'track': rec['track'], 'type': typ,
            'minutes': str(cfg['talk_lengths_min'][typ]), 'title': text['title'], 'speaker': text['speaker'],
            'affiliation': text['affiliation'], 'submitted_category': cat, 'time_windows': windows,
            'flags': sorted(set(flags))}
    abstract = {'talk_id': rec['talk_id'], 'title': text['title'], 'body': text['body'],
                'submitter_notes': text['submitter_notes']}
    if raw:
        abstract['raw'] = raw
        abstract['text_fix'] = fixes
    ref = {'talk_id': rec['talk_id'], 'session_id': rec.get('session_id', '').strip(),
           'order': rec.get('order', '').strip(), 'locked': '', 'note': (rec.get('sorter_note') or '').strip()}
    return talk, abstract, ref


def same_groups(talks, abstracts, key, flag):
    """Flag talks whose normalized title or body is identical to another talk's."""
    norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    groups = collections.defaultdict(list)
    for i, a in abstracts.items():
        k = norm(a[key])
        if len(k) > 20:
            groups[k].append(i)
    n = 0
    for ids in groups.values():
        if len(ids) > 1:
            n += 1
            for i in ids:
                talks[i]['flags'].append(f"{flag}:{'+'.join(sorted((j for j in ids if j != i), key=id_key))}")
    return n


# ---------- writing ----------
def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, lineterminator='\n', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

def read_jsonl(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}

def write_jsonl(path, recs):
    with open(path, 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def merge(old_rows, new_talks):
    """Update intake columns; keep later-stage columns and non-intake flags; never drop a talk."""
    old = {r['talk_id']: r for r in old_rows}
    out, changes = {}, collections.Counter()
    for i, t in new_talks.items():
        row = dict(old.get(i) or {c: '' for c in TALK_COLS})
        if i not in old:
            row['status'] = 'active'
            changes['added'] += 1
        elif any(row.get(c, '') != t[c] for c in INTAKE_COLS):
            changes['changed'] += 1
        row.update({c: t[c] for c in INTAKE_COLS}, talk_id=i)
        keep = [f for f in (row.get('flags') or '').split(';') if f and not f.startswith(INTAKE_FLAGS)]
        row['flags'] = ';'.join(sorted(set(keep + t['flags'])))
        out[i] = row
    for i, row in old.items():
        if i not in out:
            flags = set(filter(None, row.get('flags', '').split(';'))) | {'not_in_aps_input'}
            out[i] = dict(row, flags=';'.join(sorted(flags)))
            changes['missing from input (kept, flagged)'] += 1
    return [out[i] for i in sorted(out, key=id_key)], changes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--dry-run', action='store_true', help='report only; write nothing')
    a = ap.parse_args()
    d = a.data_dir
    cfg = yaml.safe_load(open(os.path.join(d, 'config.yaml'), encoding='utf-8'))
    colmap = {k.strip(): v for k, v in (cfg.get('aps_columns') or {}).items()}
    bad = set(colmap.values()) - FIELDS
    if bad:
        sys.exit(f'aps_columns maps to unknown fields {sorted(bad)}; allowed: {sorted(FIELDS)}')
    missing = REQUIRED - set(colmap.values())
    if missing:
        sys.exit(f'aps_columns has no column for {sorted(missing)}')

    print('Reading APS input')
    recs = []
    for track, spec in (cfg.get('aps_input') or {}).items():
        recs += read_track(d, track, spec, colmap)
    dup = [i for i, n in collections.Counter(r['talk_id'] for r in recs).items() if n > 1]
    if dup:
        sys.exit(f'talk IDs appear more than once: {dup[:20]}')

    talks, abstracts, refs = {}, {}, []
    for r in recs:
        t, ab, ref = process(r, cfg)
        talks[t['talk_id']], abstracts[t['talk_id']] = t, ab
        if ref['session_id'] or ref['order'] or ref['note']:
            refs.append(ref)
    n_same_abs = same_groups(talks, abstracts, 'body', 'same_abstract')
    n_same_title = same_groups(talks, abstracts, 'title', 'same_title')

    # keep abstracts the lead has fixed by hand
    old_abs = read_jsonl(os.path.join(d, 'abstracts.jsonl'))
    kept = [i for i, r in old_abs.items() if i in abstracts and any(x.get('by') != 'intake' for x in r.get('text_fix', []))]
    for i in kept:
        abstracts[i] = old_abs[i]
    for i, r in old_abs.items():
        abstracts.setdefault(i, r)

    rows, changes = merge(read_csv(os.path.join(d, 'talks.csv')), talks)

    flags = collections.Counter(f.split(':')[0] for r in rows for f in r['flags'].split(';') if f)
    print(f"\nTalks: {len(rows)} ({', '.join(f'{k} {v}' for k, v in collections.Counter((r['track'], r['type']) for r in rows).items())})")
    print('Changes vs existing talks.csv:', dict(changes) or 'none')
    print(f'Identical abstracts: {n_same_abs} groups; identical titles: {n_same_title} groups')
    print('Flags:', dict(sorted(flags.items())))
    fixes = collections.Counter((x['field'], x['fix']) for r in abstracts.values() for x in r.get('text_fix', []) if x['by'] == 'intake')
    for (f, w), n in sorted(fixes.items()):
        print(f'  {w}: {f} x{n}')
    if kept:
        print(f'Kept {len(kept)} hand-fixed abstracts unchanged: {kept[:10]}')
    if refs:
        print(f'Session assignments found in input: {len(refs)} talks -> reference/aps_assignments.csv')

    if a.dry_run:
        print('\n--dry-run: nothing written')
        return
    write_csv(os.path.join(d, 'talks.csv'), TALK_COLS, rows)
    write_jsonl(os.path.join(d, 'abstracts.jsonl'), [abstracts[i] for i in sorted(abstracts, key=id_key)])
    if refs:
        write_csv(os.path.join(d, 'reference', 'aps_assignments.csv'), REF_COLS, sorted(refs, key=lambda r: id_key(r['talk_id'])))
    print(f'\nWrote talks.csv and abstracts.jsonl in {d}')


if __name__ == '__main__':
    main()
