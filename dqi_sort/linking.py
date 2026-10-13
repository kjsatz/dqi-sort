"""Stage 3: link multi-part series and map affiliations to institutions.

    python -m dqi_sort.linking prepare DATA_DIR
    python -m dqi_sort.linking apply DATA_DIR

prepare writes DATA_DIR/work/linking/:
    series_candidates.md   every talk that may be one part of a series (its card says so, its title says
                           "Part ...", or it shares its abstract with another talk), with title, speaker,
                           category, the card's hints and constraints, grouped into proposed series
    pair_requests.md       every talk whose submitter asks to follow, precede or share a session with another
                           talk, with the talks the request seems to name; a clear request becomes a two-part
                           series in the order asked (PROCESS.md, Presentation cards)
    affiliations.txt       every distinct submitted affiliation, with its number of talks
    affiliations_new.txt   (with --seed OTHER/institutions.csv) the affiliations no earlier year mapped; the known
                           ones are written to institutions.csv

Claude reviews these and writes the decisions into the data repo:
    linking/series.csv     series_id, talk_id, part, sure (yes / no), note (pairs from requests: note "pair request")
    institutions.csv       affiliation, institution
    linking/institution_overrides.csv   (optional) talk_id, institution, note: for talks whose affiliation
                           string does not settle the institution (e.g. "NIST" with no site)

apply checks both files and fills series, series_part and institution in talks.csv; talks in a series
that is not sure get the flag series_uncertain, for the lead.
"""
import argparse, collections, csv, json, os, re, sys

PART = re.compile(r'\b(?:part|pt\.?)\s*[-:#]?\s*(\d+|i{1,3}|iv|one|two|three|four)\b', re.I)
PAIR_WORDS = re.compile(r'follow|precede|before|after|same session|together|adjacent|consecutive|next to|back.to.back|'
                        r'right after|immediately|in sequence|same as', re.I)
ROMAN = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'one': 1, 'two': 2, 'three': 3, 'four': 4}


def id_key(i):
    return (len(i), i)


def read_csv(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, cols, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, lineterminator='\n', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}


def affiliation_key(a):
    """Affiliation for matching: invisible characters and spacing ignored, so intake clean-ups do not break it."""
    return re.sub(r'\s+', ' ', re.sub('[\u200b\u200c\u200d\u2060\ufeff]', '', a or '')).strip().lower()


def stem(title):
    """Title without its part marker, lowercased, for matching parts of one series."""
    t = PART.split(title)[0] if PART.search(title) else title
    return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


def title_part(title):
    m = PART.search(title)
    if not m:
        return None
    v = m.group(1).lower()
    return int(v) if v.isdigit() else ROMAN.get(v)


# ---------- prepare ----------
def prepare(data_dir, seed=()):
    talks = {r['talk_id']: r for r in read_csv(os.path.join(data_dir, 'talks.csv'))}
    cards = read_jsonl(os.path.join(data_dir, 'cards.jsonl'))
    active = [i for i in talks if talks[i]['status'] == 'active']
    same = {i: [p for f in talks[i]['flags'].split(';') if f.startswith('same_abstract:') for p in f.split(':', 1)[1].split('+')]
            for i in active}
    cand = [i for i in active if (cards.get(i) or {}).get('multi_part') or title_part(talks[i]['title']) or same[i]]
    cset = set(cand)
    # proposed groups: same title stem, same abstract, or a partner hint naming the other talk's speaker or title
    adj = collections.defaultdict(set)
    for i in cand:
        for j in same[i]:
            if j in cset:
                adj[i].add(j); adj[j].add(i)
    by_stem = collections.defaultdict(list)
    for i in cand:
        s = stem(talks[i]['title'])
        if len(s) > 15:
            by_stem[s].append(i)
    for ids in by_stem.values():
        for j in ids[1:]:
            adj[ids[0]].add(j); adj[j].add(ids[0])
    for i in cand:
        hint = ' '.join(filter(None, [((cards.get(i) or {}).get('multi_part') or {}).get('partner_hint') or '',
                                      (cards.get(i) or {}).get('constraints') or ''])).lower()
        if not hint:
            continue
        for j in cand:
            if j == i:
                continue
            last = talks[j]['speaker'].split()[-1].lower() if talks[j]['speaker'] else ''
            s = stem(talks[j]['title'])
            if (len(last) > 3 and re.search(r'\b' + re.escape(last) + r'\b', hint)) or (len(s) > 20 and s in re.sub(r'[^a-z0-9]+', ' ', hint)):
                adj[i].add(j); adj[j].add(i)
    groups, seen = [], set()
    for i in sorted(cand, key=id_key):
        if i in seen:
            continue
        comp, stack = [], [i]
        while stack:
            k = stack.pop()
            if k in seen:
                continue
            seen.add(k); comp.append(k); stack += adj[k]
        groups.append(sorted(comp, key=id_key))
    groups.sort(key=lambda g: (len(g) == 1, id_key(g[0])))
    out = os.path.join(data_dir, 'work', 'linking')
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'series_candidates.md'), 'w', encoding='utf-8') as f:
        f.write(f'# Series candidates: {len(cand)} talks in {sum(len(g) > 1 for g in groups)} proposed groups '
                f'and {sum(len(g) == 1 for g in groups)} singletons\n\n')
        for n, g in enumerate(groups, 1):
            f.write(f"## {'Group' if len(g) > 1 else 'Single'} {n}\n")
            for i in g:
                t, c = talks[i], cards.get(i) or {}
                mp = c.get('multi_part')
                f.write(f"- {i} | {t['type']} | {t['submitted_category']} | {t['speaker']} | {t['affiliation'][:50]} | {t['title']}\n")
                if mp:
                    f.write(f"  - card: part {mp.get('part')} of {mp.get('of')}; hint: {mp.get('partner_hint')}\n")
                if c.get('constraints'):
                    f.write(f"  - constraints: {c['constraints']}\n")
                if same[i]:
                    f.write(f"  - same abstract as: {' '.join(same[i])}\n")
            f.write('\n')
    write_pair_requests(out, talks, cards, active)
    aff = collections.Counter(talks[i]['affiliation'] for i in active)
    with open(os.path.join(out, 'affiliations.txt'), 'w', encoding='utf-8') as f:
        for a, n in sorted(aff.items(), key=lambda kv: kv[0].lower()):
            f.write(f'{n}\t{a}\n')
    if seed:                     # institutions.csv files of other years: reuse their mappings, list only the new ones
        ipath = os.path.join(data_dir, 'institutions.csv')
        known = {affiliation_key(r['affiliation']): r for r in read_csv(ipath)} if os.path.exists(ipath) else {}
        for path in seed:
            for r in read_csv(path):
                known.setdefault(affiliation_key(r['affiliation']), r)
        rows = {}
        for a in aff:
            r = known.get(affiliation_key(a))
            if r:
                rows[a] = {'affiliation': a, 'institution': r['institution']}
        write_csv(ipath, ['affiliation', 'institution'], sorted(rows.values(), key=lambda r: r['affiliation'].lower()))
        new = {a: n for a, n in aff.items() if a not in rows}
        with open(os.path.join(out, 'affiliations_new.txt'), 'w', encoding='utf-8') as f:
            for a, n in sorted(new.items(), key=lambda kv: kv[0].lower()):
                f.write(f'{n}\t{a}\n')
        print(f'{len(rows)} affiliations mapped from earlier years; {len(new)} new ones in affiliations_new.txt')
    print(f'{len(cand)} series candidates in {sum(len(g) > 1 for g in groups)} proposed groups '
          f'(+{sum(len(g) == 1 for g in groups)} singletons); {len(aff)} distinct affiliations -> {out}')


def named_talks(text, i, talks, active):
    """Active talks other than i whose speaker surname or title stem appears in text."""
    low = text.lower()
    flat = re.sub(r'[^a-z0-9]+', ' ', low)
    out = []
    for j in active:
        if j == i:
            continue
        last = talks[j]['speaker'].split()[-1].lower() if talks[j]['speaker'] else ''
        s = stem(talks[j]['title'])
        if (len(last) > 3 and re.search(r'\b' + re.escape(last) + r'\b', low)) or (len(s) > 20 and s in flat):
            out.append(j)
    return out


def write_pair_requests(out, talks, cards, active):
    reqs = [i for i in active if PAIR_WORDS.search((cards.get(i) or {}).get('constraints') or '')]
    with open(os.path.join(out, 'pair_requests.md'), 'w', encoding='utf-8') as f:
        f.write(f'# Pair requests: {len(reqs)} talks whose submitter asks for a place next to or with another talk\n\n'
                'A clear request naming one talk becomes a two-part series in the order asked (note "pair request"). '
                'Requests about days or times only, or naming a talk not at the meeting, are left alone.\n\n')
        for i in sorted(reqs, key=id_key):
            t = talks[i]
            f.write(f"## {i} | {t['speaker']} | {t['title']}\n- request: {cards[i]['constraints']}\n")
            if t['series']:
                f.write(f"- already in series {t['series']} (part {t['series_part']})\n")
            for j in named_talks(cards[i]['constraints'], i, talks, active):
                u = talks[j]
                f.write(f"- names? {j} | {u['speaker']} | {u['title']}" + (f" | series {u['series']}" if u['series'] else '') + '\n')
            f.write('\n')
    return reqs


# ---------- apply ----------
def apply(data_dir):
    path = os.path.join(data_dir, 'talks.csv')
    rows = read_csv(path)
    cols = list(rows[0].keys())
    talks = {r['talk_id']: r for r in rows}
    errs = []
    series = read_csv(os.path.join(data_dir, 'linking', 'series.csv'))
    seen = collections.Counter(r['talk_id'] for r in series)
    errs += [f'talk {i} is in more than one series' for i, n in seen.items() if n > 1]
    errs += [f"unknown talk {r['talk_id']}" for r in series if r['talk_id'] not in talks]
    groups = collections.defaultdict(list)
    for r in series:
        groups[r['series_id']].append(r)
    for sid, rs in groups.items():
        if len(rs) < 2:
            errs.append(f'series {sid} has only one talk')
        parts = sorted(int(r['part']) for r in rs)
        if parts != list(range(1, len(rs) + 1)):
            errs.append(f'series {sid} parts are {parts}, not 1..{len(rs)}')
    inst = {affiliation_key(r['affiliation']): r['institution'] for r in read_csv(os.path.join(data_dir, 'institutions.csv'))}
    missing = sorted({t['affiliation'] for t in rows if t['status'] == 'active' and affiliation_key(t['affiliation']) not in inst})
    errs += [f'affiliation not in institutions.csv: {a!r}' for a in missing[:20]]
    if errs:
        for e in errs:
            print('ERROR', e)
        sys.exit(f'{len(errs)} errors; nothing written')
    ov_path = os.path.join(data_dir, 'linking', 'institution_overrides.csv')
    overrides = {r['talk_id']: r['institution'] for r in read_csv(ov_path)} if os.path.exists(ov_path) else {}
    bad = [i for i in overrides if i not in talks]
    if bad:
        sys.exit(f'institution overrides for unknown talks: {bad}')
    member = {r['talk_id']: r for r in series}
    unsure = {sid for sid, rs in groups.items() if any(r['sure'].strip().lower() != 'yes' for r in rs)}
    for t in rows:
        r = member.get(t['talk_id'])
        t['series'], t['series_part'] = (r['series_id'], r['part']) if r else ('', '')
        flags = [f for f in t['flags'].split(';') if f and f != 'series_uncertain']
        if r and r['series_id'] in unsure:
            flags.append('series_uncertain')
        t['flags'] = ';'.join(sorted(flags))
        t['institution'] = overrides.get(t['talk_id']) or inst.get(affiliation_key(t['affiliation']), t['institution'])
    write_csv(path, cols, rows)
    n_inst = len({t['institution'] for t in rows if t['institution']})
    print(f'{len(groups)} series ({len(unsure)} uncertain) covering {len(series)} talks; '
          f'{len(inst)} affiliations -> {n_inst} institutions ({len(overrides)} per-talk overrides); talks.csv updated')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['prepare', 'apply'])
    ap.add_argument('data_dir')
    ap.add_argument('--seed', action='append', default=[], help='prepare: institutions.csv of another year to reuse')
    a = ap.parse_args()
    prepare(a.data_dir, a.seed) if a.cmd == 'prepare' else apply(a.data_dir)


if __name__ == '__main__':
    main()
