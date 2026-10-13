"""Stage 4: propose review areas and collect the talks that need the lead's decision.

    python -m dqi_sort.areas propose DATA_DIR [--dry-run]

Areas are defined in config.yaml (`areas`: code -> name, the DQI categories it takes, and optionally the
physical `modality` of a platform area: superconducting, spin, defect or amo). Each talk starts
in the area of its card's best_category (its content, not where it was submitted). Then, using the card
embeddings, a talk whose nearest neighbours mostly sit in one other area (MOVE_VOTES of K) is moved there,
unless that would take it to another physical modality its own platform does not name.
All parts of a series go to the area of part 1. Virtual talks go to VIRTUAL.

Writes the area column of talks.csv (locked talks are left alone), and two generated views:
    views/areas.md   each area's size (talks, minutes, about how many sessions), the categories behind it,
                     and every talk the neighbour check moved
    views/flags.md   what the lead must decide: the not-DQI list, leadership review, malformed text, uncertain
                     series, duplicate submissions; plus the "could fit" other-unit notes
    work/areas/not_dqi_candidates.md   talks that may not belong in DQI at all: the card says another unit is
                     where it belongs, or it says another unit could fit and the talk has few close neighbours in
                     DQI (bottom ISOLATED_PCT of the card embeddings). Claude reads these and writes the clear
                     cases, with reasons, to sorting/not_dqi.csv (talk_id, unit, reason); flags.md lists them first.
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


def not_dqi_candidates(data_dir, talks, cards, iso, area):
    cut = np.percentile(list(iso.values()), ISOLATED_PCT)
    out = []
    for i in sorted(talks, key=id_key):
        o = (cards.get(i) or {}).get('other_unit') or {}
        if o.get('strength') == 'belongs there' or (o.get('strength') == 'could fit' and iso.get(i, 1) < cut):
            out.append(i)
    d = os.path.join(data_dir, 'work', 'areas')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'not_dqi_candidates.md'), 'w', encoding='utf-8') as f:
        f.write(f'# Not-DQI candidates ({len(out)})\n\nKeep only the clear cases (a handful): talks with no real home in a '
                'quantum-information meeting. Write them to sorting/not_dqi.csv (talk_id, unit, reason).\n\n')
        for i in out:
            t, c = talks[i], cards[i]
            f.write(f"## {i} | {area.get(i, '')} | {t['title']}\n- {c['platform']} | {c['problem']} | {c['approach']}\n"
                    f"- claim: {c['key_claim']}\n- other unit: {c['other_unit']['unit']} ({c['other_unit']['strength']}): "
                    f"{c['other_unit']['reason']}\n- similarity to 5 nearest DQI talks: {iso.get(i, 0):.3f} (cut {cut:.3f})\n\n")
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

    def row(i, extra):
        t = talks[i]
        return f"| {i} | {t['type']} | {area[i]} | {t['title'][:80]} | {extra} |"
    head = '| Talk | Type | Area | Title | Note |\n|---|---|---|---|---|'
    sec = []
    nd_path = os.path.join(data_dir, 'sorting', 'not_dqi.csv')
    nd = [r for r in read_csv(nd_path) if r['talk_id'] in talks] if os.path.exists(nd_path) else []
    sec += [f'## Not DQI? ({len(nd)})', '', 'Proposed for removal now, so they do not linger in the sort: the talk has no real home in '
            'DQI. Decide each; a removed talk gets status other_unit (with the unit in its notes). Candidates Claude '
            'considered are in work/areas/not_dqi_candidates.md.', '', head]
    sec += [row(r['talk_id'], f"{r['unit']}: {r['reason']}") for r in nd]
    nd_ids = {r['talk_id'] for r in nd}
    sec.append('')
    lr = [i for i in talks if (cards.get(i) or {}).get('leadership_review')]
    sec += [f'## Leadership review ({len(lr)})', '', 'The card says the talk may not meet the standard for an oral talk.', '', head]
    sec += [row(i, cards[i]['leadership_review']['reason']) for i in sorted(lr, key=id_key)]
    bt = [i for i in talks if ((cards.get(i) or {}).get('other_unit') or {}).get('strength') == 'belongs there' and i not in nd_ids]
    sec += ['', f'## Card says another unit (not on the not-DQI list) ({len(bt)})', '', 'Claude judged these fit DQI after all; '
            'they stay unless you say otherwise.', '', head]
    sec += [row(i, f"{cards[i]['other_unit']['unit']}: {cards[i]['other_unit']['reason']}") for i in sorted(bt, key=id_key)]
    mf = [i for i in talks if (cards.get(i) or {}).get('malformed')]
    sec += ['', f'## Malformed text ({len(mf)})', '', 'Still damaged after intake and Claude\'s repair: fixing these would need a missing value. '
            'Fix by hand if you know it (`dqi_sort.fixes apply`), or leave it.', '', head]
    sec += [row(i, cards[i]['malformed']['issue'] + (f" Suggested: {cards[i]['malformed']['suggested_fix']}" if cards[i]['malformed'].get('suggested_fix') else ''))
            for i in sorted(mf, key=id_key)]
    su = collections.defaultdict(list)
    for i, t in talks.items():
        if 'series_uncertain' in t['flags']:
            su[t['series']].append(i)
    sec += ['', f'## Uncertain series ({len(su)})', '', 'Confirm or fix in linking/series.csv.', '', head]
    for s, ids in sorted(su.items()):
        for i in sorted(ids, key=lambda i: int(talks[i]['series_part'])):
            sec.append(row(i, f"{s} part {talks[i]['series_part']}"))
    dup = [i for i in talks if not talks[i]['series'] and any(
        p in talks for f in talks[i]['flags'].split(';') if f.startswith('same_title:') for p in f.split(':', 1)[1].split('+'))]
    sec += ['', f'## Possible duplicate submissions ({len(dup)})', '', 'Same title as another talk and not a series.', '', head]
    sec += [row(i, ' '.join(f for f in talks[i]['flags'].split(';') if f.startswith('same_'))) for i in sorted(dup, key=id_key)]
    by_speaker = collections.defaultdict(list)
    for i, t in talks.items():
        if t['speaker'].strip():
            by_speaker[t['speaker'].strip().lower()].append(i)
    ss = sorted((ids for ids in by_speaker.values() if len(ids) > 1 and any(talks[i]['type'] == 'invited' for i in ids)
                 and len({talks[i]['series'] for i in ids if talks[i]['series']}) <= 1 and not all(talks[i]['series'] for i in ids)),
                key=lambda ids: id_key(ids[0]))
    sec += ['', f'## Invited speaker with another talk ({len(ss)})', '', 'Often one talk entered twice (an invited placeholder '
            'and the real submission); otherwise two talks the scheduler must keep apart.', '', head]
    sec += [row(i, f"same speaker: {talks[i]['speaker']}") for ids in ss for i in sorted(ids, key=id_key)]
    cf = [i for i in talks if ((cards.get(i) or {}).get('other_unit') or {}).get('strength') == 'could fit']
    by_unit = collections.Counter(cards[i]['other_unit']['unit'] for i in cf)
    sec += ['', f'## Could also fit another unit ({len(cf)}; no action needed)', '',
            ', '.join(f'{u} {c}' for u, c in by_unit.most_common()) + '. These stay in DQI unless a talk is left over with nowhere good to go.']
    rep = [(i, x) for i in sorted(talks, key=id_key) for x in (abstracts.get(i) or {}).get('text_fix', []) if x.get('by') == 'claude']
    sec += ['', f'## Repaired automatically ({len({i for i, _ in rep})} talks, {len(rep)} edits; spot-check)', '',
            'Claude\'s mechanical repairs (prompts/repair_spec.md); the original text is in `raw` in abstracts.jsonl.', '',
            '| Talk | Field | Repair |', '|---|---|---|']
    sec += [f"| {i} | {x['field']} | {x['fix']} |" for i, x in rep]
    total = len(nd) + len(lr) + len(bt) + len(mf) + len(su) + len(dup) + len(ss)
    with open(os.path.join(data_dir, 'views', 'flags.md'), 'w', encoding='utf-8') as f:
        f.write('# Flags for the lead (stage 4 checkpoint)\n\nGenerated by `python -m dqi_sort.areas propose`; do not edit. '
                f'{total} items to decide.\n\n' + '\n'.join(sec) + '\n')
    return n, mins


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
    nd = not_dqi_candidates(data_dir, talks, cards, isolation(ids, X, inperson), area)
    n, mins = write_views(data_dir, talks, cards, areas, area, moves, abstracts)
    for a in areas:
        print(f'  {a:8s} {n[a]:4d} talks {mins[a]:6d} min  ~{mins[a] / TYPICAL_SESSION_MIN:.0f} sessions')
    print(f"{sum(1 for m in moves if m[3] != 'series')} talks moved by the neighbour check, "
          f"{sum(1 for m in moves if m[3] == 'series')} to keep series together; views/areas.md, views/flags.md written; "
          f"{len(nd)} not-DQI candidates in work/areas/not_dqi_candidates.md")
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
    ap.add_argument('cmd', choices=['propose'])
    ap.add_argument('data_dir')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    propose(a.data_dir, a.dry_run)


if __name__ == '__main__':
    main()
