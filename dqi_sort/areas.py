"""Stage 4: propose review areas and collect the talks that need the lead's decision.

    python -m dqi_sort.areas propose DATA_DIR [--dry-run]
    python -m dqi_sort.areas flags DATA_DIR

Areas are defined in config.yaml (`areas`: code -> name, the DQI categories it takes, and optionally the
physical `modality` of a platform area: superconducting, spin, defect or amo). Each talk starts
in the area of its card's best_category (its content, not where it was submitted). Then, using the card
embeddings, a talk whose nearest neighbours mostly sit in one other area (MOVE_VOTES of K) is moved there,
unless that would take it to another physical modality its own platform does not name.
All parts of a series go to the area of part 1. Virtual talks go to VIRTUAL.

Writes the area column of talks.csv (locked talks are left alone), and two generated views:
    views/areas.md   each area's size (talks, minutes, about how many sessions), the categories behind it,
                     and every talk the neighbour check moved
    views/flags.md   the one list of talks the lead must decide, each listed once: talks held for the lead
                     (sorting/held.csv, with card and proposal), non-scientific content, too little text to place, uncertain
                     series, duplicate submissions; then, for information, promotional abstracts and "could fit"
                     other-unit notes. `flags` rewrites it alone (pack finish runs it too).
    work/areas/held_candidates.md   in-person talks that may leave the oral program: the card says another unit is
                     where it belongs, or that another unit could fit and the talk has few close neighbours in DQI
                     (bottom ISOLATED_PCT of the card embeddings), or that it may have no scientific content. Claude
                     reads these and writes the clear cases to sorting/held.csv (talk_id, stage 4, action other_unit
                     with the unit, or poster; reason). Virtual talks are never listed.
"""
import argparse, collections, csv, json, os, re, sys
import numpy as np
import yaml
from dqi_sort.embed import load as load_embeddings

K = 10
MOVE_VOTES = 7
# Physical modality of a card's platform, from its wording. Areas may declare a `modality` in config.yaml;
# the neighbour check moves a talk between areas of different modalities only if its own platform names the
# destination modality, so talks stay with their physical platform by default (a bosonic code on trapped
# ions stays with atoms and photons even if its nearest neighbours are superconducting bosonic codes).
MODALITY_WORDS = {
    'superconducting': r'supercond|transmon|fluxonium|josephson|circuit qed|cqed|\bsquid|kinetic inductance|\btwpa|\bjpa|granular alumin|tantalum|niobium',
    'spin': r'quantum dot|spin qubit|donor|silicon|germanium|\bsige\b|gate-defined|exchange-only|singlet-triplet|hole spin',
    'defect': r'\bnv\b|nitrogen.vacancy|diamond|color cent|colour cent|silicon carbide|\bsic\b|defect|rare.earth|erbium|\bhbn\b|vacanc|magnon',
    'amo': r'\bions?\b|trapped.ion|atom|rydberg|tweezer|optical|laser|molecul|\bbec\b|photonic|single.photon source|telecom',
}
TYPICAL_SESSION_MIN = 126    # average of 144 and 108
ISOLATED_PCT = 5             # "few close neighbours": bottom 5% by mean similarity to the 5 nearest talks
BRIDGE_SHARE = 0.7           # a bridge talk has at least this share of its K nearest neighbours in other areas


def id_key(i):
    return (len(i), i)


def read_csv(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def assign(talks, cards, areas, ids, X):
    """Return ({talk_id: area}, [moves]) for active talks."""
    by_cat = {c: a for a, v in areas.items() for c in v['categories']}
    area = {}
    for i, t in talks.items():
        if t['track'] == 'virtual':
            area[i] = 'VIRTUAL'
        else:
            area[i] = by_cat.get(cards[i]['best_category'], 'FOUND') if i in cards else 'FOUND'
    moves = []
    idx = {i: k for k, i in enumerate(ids)}
    inperson = [i for i in ids if i in talks and talks[i]['track'] == 'in_person']
    sub = np.array([idx[i] for i in inperson])
    S = X[sub] @ X[sub].T
    np.fill_diagonal(S, -np.inf)
    nn = np.argsort(-S, axis=1)[:, :K]
    start = dict(area)
    modality = {a: v.get('modality') for a, v in areas.items()}
    for r, i in enumerate(inperson):
        votes = collections.Counter(start[inperson[j]] for j in nn[r])
        top, n = votes.most_common(1)[0]
        if top == start[i] or n < MOVE_VOTES:
            continue
        a, b = modality.get(start[i]), modality.get(top)
        if a and b and a != b:                # a different physical platform: move only if the card's platform says so
            plat = (cards.get(i) or {}).get('platform', '')
            names = lambda m: bool(re.search(MODALITY_WORDS.get(m, '$^'), plat, re.I))
            if not names(b) or names(a):
                continue
        area[i] = top
        moves.append((i, start[i], top, n))
    series = collections.defaultdict(list)
    for i, t in talks.items():
        if t['series']:
            series[t['series']].append((int(t['series_part']), i))
    for parts in series.values():
        parts.sort()
        for _, i in parts[1:]:
            if talks[i]['track'] != talks[parts[0][1]]['track']:     # never across tracks (linking refuses such series)
                continue
            if area[i] != area[parts[0][1]]:
                moves.append((i, area[i], area[parts[0][1]], 'series'))
                area[i] = area[parts[0][1]]
    return area, moves


def isolation(ids, X, keep):
    """{talk_id: mean cosine similarity to its 5 nearest talks among keep}."""
    idx = [k for k, i in enumerate(ids) if i in keep]
    Y = X[idx].astype(float)
    S = Y @ Y.T
    np.fill_diagonal(S, -np.inf)
    top = -np.sort(-S, axis=1)[:, :5]
    return {ids[k]: float(v) for k, v in zip(idx, top.mean(axis=1))}


def neighbour_areas(ids, X, area):
    """{talk_id: Counter of the areas of its K nearest neighbours that are not its own area}, for talks in area."""
    idx = [k for k, i in enumerate(ids) if i in area]
    Y = X[idx].astype(float)
    S = Y @ Y.T
    np.fill_diagonal(S, -np.inf)
    nn = np.argsort(-S, axis=1)[:, :K]
    out = {}
    for r, k in enumerate(idx):
        i = ids[k]
        out[i] = collections.Counter(a for a in (area[ids[idx[j]]] for j in nn[r]) if a != area[i])
    return out


def bridge(counts):
    """Bridge talks from neighbour_areas: {talk_id: 'near SCMAT 6/10, QEC 2/10'}."""
    return {i: 'near ' + ', '.join(f'{a} {n}/{K}' for a, n in c.most_common())
            for i, c in counts.items() if sum(c.values()) >= BRIDGE_SHARE * K}


HELD_COLS = ['talk_id', 'stage', 'action', 'unit', 'reason']
ACTION_TEXT = {'poster': 'make it a poster', 'other_unit': 'send to another unit', 'decide': 'no proposal: the lead decides'}


def read_held(data_dir):
    path = os.path.join(data_dir, 'sorting', 'held.csv')
    return read_csv(path) if os.path.exists(path) else []


def write_held(data_dir, rows):
    os.makedirs(os.path.join(data_dir, 'sorting'), exist_ok=True)
    with open(os.path.join(data_dir, 'sorting', 'held.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, HELD_COLS, extrasaction='ignore', lineterminator='\n')
        w.writeheader(); w.writerows(sorted(rows, key=lambda r: id_key(r['talk_id'])))


def held_candidates(data_dir, talks, cards, iso, area):
    """In-person talks that may leave DQI's oral program: another unit, or a poster. Virtual talks are never listed."""
    cut = np.percentile(list(iso.values()), ISOLATED_PCT)
    out = []
    for i in sorted(talks, key=id_key):
        if talks[i]['track'] != 'in_person':
            continue
        c = cards.get(i) or {}
        o = c.get('other_unit') or {}
        if c.get('leadership_review') or o.get('strength') == 'belongs there':
            out.append(i)
    d = os.path.join(data_dir, 'work', 'areas')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'held_candidates.md'), 'w', encoding='utf-8') as f:
        f.write(f'# Talks that may leave the oral program ({len(out)})\n\nWe keep talks in DQI unless they really do not belong: past '
                'human sorts sent away 0 to 3 talks a year, so expect about that many. Write them to sorting/held.csv (talk_id, '
                'stage 4, action, unit, reason): action other_unit, with the unit, only for a talk with no quantum-information '
                'content at all (classical machine learning, nuclear structure, classical fluids) that is squarely another unit\'s '
                'field; a talk on quantum physics that sits near another field stays. Action poster only for a talk with no scientific content at all (an essay, '
                'or claims outside physics with no physics argument). Bold claims, unconventional foundations and a promotional tone are no reason to list '
                'a talk. Virtual talks are never listed: the virtual track keeps every talk.\n\n')
        for i in out:
            t, c = talks[i], cards[i]
            f.write(f"## {i} | {area.get(i, '')} | {t['title']}\n- {c['platform']} | {c['problem']} | {c['approach']}\n"
                    f"- claim: {c['key_claim']}\n")
            if c.get('other_unit'):
                f.write(f"- other unit: {c['other_unit']['unit']} ({c['other_unit']['strength']}): {c['other_unit']['reason']}\n")
            if c.get('leadership_review'):
                f.write(f"- non-scientific? {c['leadership_review']['reason']}\n")
            f.write(f"- similarity to 5 nearest DQI talks: {iso.get(i, 0):.3f} (cut {cut:.3f})\n\n")
    return out


def write_views(data_dir, talks, cards, areas, area, moves, abstracts=None):
    abstracts = abstracts or {}
    os.makedirs(os.path.join(data_dir, 'views'), exist_ok=True)
    mins, n = collections.Counter(), collections.Counter()
    for i, t in talks.items():
        mins[area[i]] += int(t['minutes']); n[area[i]] += 1
    lines = ['# Review areas (proposed)', '',
             'Generated by `python -m dqi_sort.areas propose`; do not edit. Each talk starts in the area of its card\'s '
             f'best category, then moves if {MOVE_VOTES} of its {K} nearest neighbours (card embeddings) are in one other area; '
             'series stay together.', '',
             '| Area | Name | Talks | Minutes | ≈ Sessions |', '|---|---|---|---|---|']
    for a, v in areas.items():
        lines.append(f"| {a} | {v['name']} | {n[a]} | {mins[a]} | {mins[a] / TYPICAL_SESSION_MIN:.0f} |")
    lines.append(f"| | total | {sum(n.values())} | {sum(mins.values())} | |")
    lines += ['', f'## Moved by the neighbour check ({sum(1 for m in moves if m[3] != "series")}) or to keep a series together '
              f'({sum(1 for m in moves if m[3] == "series")})', '', '| Talk | From | To | Why | Title |', '|---|---|---|---|---|']
    for i, a, b, why in sorted(moves, key=lambda m: (m[1], m[2], id_key(m[0]))):
        lines.append(f"| {i} | {a} | {b} | {f'{why}/{K} neighbours' if why != 'series' else 'series'} | {talks[i]['title'][:90]} |")
    with open(os.path.join(data_dir, 'views', 'areas.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    flags(data_dir, talks, cards, area, abstracts)
    return n, mins


def flags(data_dir, talks=None, cards=None, area=None, abstracts=None):
    """Write views/flags.md: the one list of talks the lead must decide. Each talk appears in one section (a group
    section names a talk listed above but does not repeat it)."""
    if talks is None:
        talks = {r['talk_id']: r for r in read_csv(os.path.join(data_dir, 'talks.csv')) if r['status'] == 'active'}
    if cards is None:
        with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
            cards = {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}
    if area is None:
        area = {i: t['area'] for i, t in talks.items()}
    if abstracts is None:
        path = os.path.join(data_dir, 'abstracts.jsonl')
        with open(path, encoding='utf-8') as f:
            abstracts = {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}
    card = lambda i: cards.get(i) or {}
    shown = set()
    head = '| Talk | Type | Area | Title | Note |\n|---|---|---|---|---|'

    def row(i, extra):
        t = talks[i]
        return f"| {i} | {t['type']} | {area.get(i, '')} | {t['title'][:80]} | {extra} |"

    def single(title, intro, ids, note):
        ids = [i for i in sorted(ids, key=id_key) if i not in shown]
        shown.update(ids)
        return ['', f'## {title} ({len(ids)})', '', intro, '', head] + [row(i, note(i)) for i in ids]

    def group(title, intro, groups, note):
        out = ['', f'## {title} ({len(groups)})', '', intro, '', head]
        for ids in groups:
            out += [row(i, '(listed above)' if i in shown else note(i)) for i in ids]
        return out

    def other_flags(i):
        c, out = card(i), []
        if c.get('leadership_review'):
            out.append('non-scientific? ' + c['leadership_review']['reason'])
        if c.get('promotional'):
            out.append('promotional: ' + c['promotional']['reason'])
        if c.get('other_unit'):
            out.append(f"other unit {c['other_unit']['unit']} ({c['other_unit']['strength']}): {c['other_unit']['reason']}")
        if c.get('malformed'):
            out.append('too little text: ' + c['malformed']['issue'])
        out += [f for f in talks[i]['flags'].split(';') if f.startswith('same_')]
        return out

    held = [r for r in read_held(data_dir) if r['talk_id'] in talks]
    apath = os.path.join(data_dir, 'sorting', 'assignments.csv')
    placed = {r['talk_id']: r['session_id'] for r in read_csv(apath) if r['session_id']} if os.path.exists(apath) else {}
    held.sort(key=lambda r: (list(ACTION_TEXT).index(r['action']) if r['action'] in ACTION_TEXT else 9, id_key(r['talk_id'])))
    sec = [f'## Held for the lead ({len(held)})', '',
           'Talks proposed to leave the oral program, at stage 4 (before drafting) or by the global pass (talks it could not '
           'place). Decide each with `python -m dqi_sort.decide`: `offer UNIT` (set aside while another unit decides), '
           '`poster`, or `keep` (it stays; in no session it is a lonely abstract). Virtual talks are never held.', '']
    for r in held:
        i, t, c = r['talk_id'], talks[r['talk_id']], card(r['talk_id'])
        prop = ACTION_TEXT.get(r['action'], r['action']) + (f" ({r['unit']})" if r['unit'] else '')
        sec += [f"### {i}: {t['title']}", '',
                f"- **Proposal: {prop}.** {r['reason']} _({'stage 4 list' if r['stage'] == '4' else 'global pass'})_",
                f"- {t['speaker']}, {t['affiliation']}" + (f" ({t['institution']})" if t['institution'] and t['institution'] not in t['affiliation'] else ''),
                f"- {t['type']}, {t['track'].replace('_', ' ')}, area {area.get(i, '')}, submitted to {t['submitted_category']}"
                + (f"; now in session {placed[i]} (it stays there unless you decide otherwise)" if i in placed else '; in no session')]
        if c:
            sec += [f"- Card: {c['platform']} | {c['problem']} | {c['approach']}", f"- Key claim: {c['key_claim']}",
                    f"- Keywords: {'; '.join(c['keywords'])}"]
        sec += [f'- Also flagged: {x}' for x in other_flags(i)] + ['']
        shown.add(i)
    lpath = os.path.join(data_dir, 'sorting', 'status_log.csv')
    slog = read_csv(lpath) if os.path.exists(lpath) else []
    if slog:
        everyone = {r['talk_id']: r for r in read_csv(os.path.join(data_dir, 'talks.csv'))}
        last = {}
        for r in slog:
            last[r['talk_id']] = r
        pend = [r for i, r in last.items() if everyone.get(i, {}).get('status') == 'exchange_pending']
        sec += [f'## Offered to another unit, waiting ({len(pend)})', '', 'Set aside while the unit decides: `decide exchanged` '
                'when it takes the talk, `decide returned` when it does not. The full record is in sorting/status_log.csv.', '',
                '| Talk | Title | Unit | Offered | Note |', '|---|---|---|---|---|']
        sec += [f"| {r['talk_id']} | {everyone[r['talk_id']]['title'][:70]} | {r['unit']} | {r['when'].replace('T', ' ')} | {r['note']} |"
                for r in sorted(pend, key=lambda r: r['when'])]
        done = collections.Counter(r['unit'] for i, r in last.items() if everyone.get(i, {}).get('status') == 'other_unit')
        got = collections.Counter(f.split(':', 1)[1] for t in talks.values() for f in t['flags'].split(';') if f.startswith('from_unit:'))
        sec += ['', f"Exchanged to other units: {sum(done.values())}" + (f" ({', '.join(f'{u} {n}' for u, n in done.most_common())})" if done else '')
                + f". Brought in from other units: {sum(got.values())}" + (f" ({', '.join(f'{u} {n}' for u, n in got.most_common())})" if got else '') + '.', '']
    lr = [i for i in talks if card(i).get('leadership_review')]
    sec += single('Non-scientific?', 'The card found no scientific content at all (an essay, or claims outside physics with no physics argument); expect one or two a year. Bold claims and unconventional foundations are not listed. '
                  'In person: keep it (the usual outcome), or make it a poster. Virtual: it stays, at the end of a session.',
                  lr, lambda i: cards[i]['leadership_review']['reason'])
    mf = [i for i in talks if card(i).get('malformed')]
    sec += single('Too little text to place', 'The card could not tell what the talk is about (for example an invited talk listed '
                  'by speaker name only); it is placed from its category. A real title with no abstract is enough and is not listed.', mf,
                  lambda i: cards[i]['malformed']['issue'])
    su = collections.defaultdict(list)
    for i, t in talks.items():
        if 'series_uncertain' in t['flags']:
            su[t['series']].append(i)
    sec += group('Uncertain series', 'Confirm or fix in linking/series.csv.',
                 [sorted(ids, key=lambda i: int(talks[i]['series_part'])) for _, ids in sorted(su.items())],
                 lambda i: f"{talks[i]['series']} part {talks[i]['series_part']}")
    dup = collections.defaultdict(set)
    for i in talks:
        if talks[i]['series']:
            continue
        for f in talks[i]['flags'].split(';'):
            if f.startswith('same_title:'):
                ps = [p for p in f.split(':', 1)[1].split('+') if p in talks]
                if ps:
                    dup[min([i] + ps, key=id_key)].update([i] + ps)
    sec += group('Possible duplicate submissions', 'Same title as another talk and not a series.',
                 [sorted(v, key=id_key) for _, v in sorted(dup.items(), key=lambda kv: id_key(kv[0]))],
                 lambda i: ' '.join(f for f in talks[i]['flags'].split(';') if f.startswith('same_')))
    by_speaker = collections.defaultdict(list)
    for i, t in talks.items():
        if t['speaker'].strip() and t['type'] == 'invited':
            by_speaker[t['speaker'].strip().lower()].append(i)
    one_series = lambda ids: all(talks[i]['series'] for i in ids) and len({talks[i]['series'] for i in ids}) == 1
    ss = sorted((sorted(ids, key=id_key) for ids in by_speaker.values() if len(ids) > 1 and not one_series(ids)), key=lambda ids: id_key(ids[0]))
    sec += group('Invited talk entered twice?', 'The same speaker has two invited entries (often a placeholder and the real entry): '
                 '`decide duplicate KEEP OTHER`, keeping the one with more information. An invited speaker may also give a '
                 'contributed talk; such pairs are not listed.', ss, lambda i: f"same speaker: {talks[i]['speaker']}")
    bt = [i for i in talks if (card(i).get('other_unit') or {}).get('strength') == 'belongs there']
    sec += single('Card says another unit, kept in DQI', 'Claude judged these fit DQI after all; they stay unless you say otherwise.',
                  bt, lambda i: f"{cards[i]['other_unit']['unit']}: {cards[i]['other_unit']['reason']}")
    decide = len(shown)
    pr = [i for i in talks if card(i).get('promotional')]
    sec += single('Promotional (no action expected)', 'The abstract reads partly as promotion of a product, company or platform. '
                  'Common at this meeting and usually fine; listed so you can keep an eye on them.', pr, lambda i: cards[i]['promotional']['reason'])
    cf = [i for i in talks if (card(i).get('other_unit') or {}).get('strength') == 'could fit']
    by_unit = collections.Counter(cards[i]['other_unit']['unit'] for i in cf)
    sec += ['', f'## Could also fit another unit ({len(cf)}; no action needed)', '',
            ', '.join(f'{u} {c}' for u, c in by_unit.most_common()) + '. These stay in DQI unless a talk is left over with nowhere good to go.']
    os.makedirs(os.path.join(data_dir, 'views'), exist_ok=True)
    with open(os.path.join(data_dir, 'views', 'flags.md'), 'w', encoding='utf-8') as f:
        f.write('# For the lead\n\nGenerated by `python -m dqi_sort.areas flags` (also run by `areas propose` and `pack finish`); '
                f'do not edit. The one list of talks the lead must decide: {decide} talks, each listed once. Held talks come '
                'first, with their cards; the global pass report (views/packing_report.md) only counts them.\n\n' + '\n'.join(sec) + '\n')


def propose(data_dir, dry_run=False):
    with open(os.path.join(data_dir, 'config.yaml'), encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    areas = cfg.get('areas')
    if not areas:
        sys.exit('config.yaml has no areas')
    path = os.path.join(data_dir, 'talks.csv')
    rows = read_csv(path)
    cols = list(rows[0].keys())
    talks = {r['talk_id']: r for r in rows if r['status'] == 'active'}
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}
    ids, X, _ = load_embeddings(os.path.join(data_dir, 'embeddings', 'cards.npz'))
    area, moves = assign(talks, cards, areas, ids, X)
    with open(os.path.join(data_dir, 'abstracts.jsonl'), encoding='utf-8') as f:
        abstracts = {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}
    inperson = {i for i, t in talks.items() if t['track'] == 'in_person'}
    nd = held_candidates(data_dir, talks, cards, isolation(ids, X, inperson), area)
    n, mins = write_views(data_dir, talks, cards, areas, area, moves, abstracts)
    for a in areas:
        print(f'  {a:8s} {n[a]:4d} talks {mins[a]:6d} min  ~{mins[a] / TYPICAL_SESSION_MIN:.0f} sessions')
    print(f"{sum(1 for m in moves if m[3] != 'series')} talks moved by the neighbour check, "
          f"{sum(1 for m in moves if m[3] == 'series')} to keep series together; views/areas.md, views/flags.md written; "
          f"{len(nd)} candidates to leave the oral program in work/areas/held_candidates.md")
    if dry_run:
        return
    locked = 0
    for r in rows:
        if r['talk_id'] in area:
            if r['notes'].strip().lower().startswith('locked') or r.get('area_locked') == 'true':
                locked += 1
                continue
            r['area'] = area[r['talk_id']]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, lineterminator='\n')
        w.writeheader(); w.writerows(rows)
    print('talks.csv area column updated')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['propose', 'flags'])
    ap.add_argument('data_dir')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'flags':
        flags(a.data_dir)
    else:
        propose(a.data_dir, a.dry_run)


if __name__ == '__main__':
    main()
