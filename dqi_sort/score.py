"""Score a sort: embedding measures, agreement with the human sort, and a blind judge.

    python -m dqi_sort.score metrics DATA_DIR [--state work/pack/state.json] [--name NAME]
    python -m dqi_sort.score judge-prepare DATA_DIR [--n 30] [--seed 1]
    python -m dqi_sort.score judge-report DATA_DIR

Scoring is the only step that reads the human final sort (config.yaml `reference_sort`: talk_id, session_id).

metrics        for the sort in sorting/ (or a global-pass state file) and for the human sort: sessions, talks left
               out, mean coherence (each talk's similarity to the rest of its session, card embeddings), the worst
               ten sessions, the share of talks whose own session is their nearest, and the share of pairs in the
               same session that the human sort also put together. Appends a line to views/scores.md.
judge-prepare  samples n in-person sessions from Claude's sort (and from each --compare NAME=GITREV sort) and n from the human sort (at least 6 talks each,
               only talks that are in this year's input), shuffles them under neutral labels, and writes
               work/judge/sessions.md (each session's talks: title and the card's key claim; no titles, IDs or
               sources), work/judge/key.json (the labels' sources, for judge-report only) and work/judge/prompt.md.
               One Claude agent (prompts/judge_spec.md) rates every session and writes work/judge/ratings.json.
judge-report   unblinds the ratings: mean rating and out-of-place talks per 10 talks, Claude against human;
               appends to views/scores.md.
"""
import argparse, collections, csv, datetime, itertools, json, os, random, sys
import numpy as np
from dqi_sort import sessions as S
from dqi_sort.pack import Space, coherence


def active_talks(data_dir):
    return {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv')) if t['status'] == 'active'}


def human_sort(data_dir, cfg, talks):
    path = cfg.get('reference_sort')
    if not path or not os.path.exists(os.path.join(data_dir, path)):
        return None
    g = collections.defaultdict(list)
    rows = S.read_csv(os.path.join(data_dir, path))
    for r in sorted(rows, key=lambda r: (r['session_id'], float(r['order'] or 0))):
        if r['session_id'] and r['talk_id'] in talks and talks[r['talk_id']]['track'] == 'in_person':
            g[r['session_id']].append(r['talk_id'])
    return dict(g)


def claude_sort(data_dir, talks, state=None, rev=None):
    if rev:                                      # the sort as committed at a git revision of the data repo
        import io, subprocess
        txt = subprocess.run(['git', '-C', data_dir, 'show', f'{rev}:sorting/assignments.csv'], capture_output=True,
                             text=True, check=True).stdout
        rows = list(csv.DictReader(io.StringIO(txt)))
        g = collections.defaultdict(list)
        for r in sorted(rows, key=lambda r: (r['session_id'], int(r['order'] or 0))):
            if r['session_id'] and r['talk_id'] in talks and talks[r['talk_id']]['track'] == 'in_person':
                g[r['session_id']].append(r['talk_id'])
        return dict(g), sum(1 for r in rows if not r['session_id'] and r['talk_id'] in talks)
    if state:
        with open(os.path.join(data_dir, state), encoding='utf-8') as f:
            st = json.load(f)
        return {s['id']: s['talks'] for s in st['sessions']}, len(st['pool'])
    g = collections.defaultdict(list)
    lonely = 0
    for r in sorted(S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv')), key=lambda r: (r['session_id'], int(r['order'] or 0))):
        if r['talk_id'] not in talks or talks[r['talk_id']]['track'] != 'in_person':
            continue
        if r['session_id']:
            g[r['session_id']].append(r['talk_id'])
        else:
            lonely += 1
    return dict(g), lonely


def measures(space, groups, hpairs=None):
    groups = {k: [i for i in v if space.vec(i) is not None] for k, v in groups.items()}
    groups = {k: v for k, v in groups.items() if len(v) > 1}
    coh = {k: coherence(space, v)[0] for k, v in groups.items()}
    keys = list(groups)
    M = np.array([space.centroid(groups[k]) for k in keys])
    own = tot = 0
    for n, k in enumerate(keys):
        for i in groups[k]:
            x = space.vec(i)
            sims = M @ x
            sims[n] = x @ space.centroid(groups[k], leave_out=i)
            own += int(np.argmax(sims)) == n
            tot += 1
    out = {'sessions': len(groups), 'coherence': float(np.mean(list(coh.values()))),
           'worst10': float(np.mean(sorted(coh.values())[:10])), 'own_nearest': own / tot,
           'talks_per_session': tot / len(groups)}
    if hpairs is not None:
        pairs = {frozenset(p) for v in groups.values() for p in itertools.combinations(v, 2)}
        out['human_pairs'] = len(pairs & hpairs) / len(pairs)
    return out


def line(name, m, lonely):
    hp = f"{m['human_pairs']:.1%}" if 'human_pairs' in m else '—'
    return (f"| {name} | {m['sessions']} | {m['talks_per_session']:.1f} | {lonely} | {m['coherence']:.4f} | {m['worst10']:.4f} | "
            f"{m['own_nearest']:.1%} | {hp} |")


HEAD = ['| Sort | Sessions | Talks per session | Left out | Coherence | Worst 10 | Own session nearest | Pairs also together in human sort |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']


def write_scores(data_dir, lines, title):
    path = os.path.join(data_dir, 'views', 'scores.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, 'a', encoding='utf-8') as f:
        if new:
            f.write('# Scores\n\nGenerated by `dqi_sort.score`; do not edit. Coherence: mean cosine similarity (card embeddings) of '
                    'each talk to the rest of its session. Human sessions were longer (more talks), which lowers coherence.\n')
        f.write(f'\n## {title} ({datetime.date.today().isoformat()})\n\n' + '\n'.join(lines) + '\n')


def metrics(data_dir, state=None, name=None):
    cfg = S.load_config(data_dir)
    talks = active_talks(data_dir)
    space = Space(data_dir, talks)
    human = human_sort(data_dir, cfg, talks)
    hpairs = {frozenset(p) for v in human.values() for p in itertools.combinations(v, 2)} if human else None
    lines = list(HEAD)
    if human:
        lines.append(line('human final sort', measures(space, human), 0))
    g, lonely = claude_sort(data_dir, talks, state)
    lines.append(line(name or (state or 'sorting/'), measures(space, g, hpairs), lonely))
    print('\n'.join(lines))
    write_scores(data_dir, lines, f"Metrics: {name or state or 'sorting/'}")


# ---------- blind judge ----------
def judge_prepare(data_dir, n=30, seed=1, compare=()):
    cfg = S.load_config(data_dir)
    talks = active_talks(data_dir)
    human = human_sort(data_dir, cfg, talks)
    if not human:
        sys.exit('no reference_sort for this year: the blind judge needs the human sort')
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    mine, _ = claude_sort(data_dir, talks)
    rnd = random.Random(seed)
    pick = lambda g: rnd.sample(sorted(k for k, v in g.items() if len(v) >= 6), min(n, sum(len(v) >= 6 for v in g.values())))
    items = [('claude', k, mine[k]) for k in pick(mine)] + [('human', k, human[k]) for k in pick(human)]
    for spec in compare:                         # NAME=GITREV, or NAME=state:PATH (a global-pass state file)
        name, rev = spec.split('=', 1)
        other, _ = (claude_sort(data_dir, talks, state=rev[6:]) if rev.startswith('state:') else claude_sort(data_dir, talks, rev=rev))
        items += [(name, k, other[k]) for k in pick(other)]
    rnd.shuffle(items)
    d = os.path.join(data_dir, 'work', 'judge')
    os.makedirs(d, exist_ok=True)
    key, out = {}, ['# Sessions to rate', '']
    for k, (src, sid, ids) in enumerate(items, 1):
        lab = f'J{k:02d}'
        key[lab] = {'source': src, 'session': sid, 'talks': len(ids)}
        out.append(f'## {lab} ({len(ids)} talks)')
        for i in ids:
            t, c = talks[i], cards.get(i) or {}
            inv = ' [invited]' if t['type'] == 'invited' else ''
            out.append(f"- {i}{inv}: {t['title']} — {c.get('key_claim', '')}")
        out.append('')
    with open(os.path.join(d, 'sessions.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    with open(os.path.join(d, 'key.json'), 'w', encoding='utf-8') as f:
        json.dump(key, f, indent=1)
    with open(os.path.join(S.HERE, 'prompts', 'judge_spec.md'), encoding='utf-8') as f:
        spec = f.read()
    with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
        f.write(spec.replace('{DIR}', os.path.abspath(d)).replace('{N}', str(len(items))))
    print(f'{len(items)} sessions ({sum(x[0] == "claude" for x in items)} Claude, {sum(x[0] == "human" for x in items)} human) in {d}')


def judge_report(data_dir):
    d = os.path.join(data_dir, 'work', 'judge')
    with open(os.path.join(d, 'key.json'), encoding='utf-8') as f:
        key = json.load(f)
    with open(os.path.join(d, 'ratings.json'), encoding='utf-8') as f:
        ratings = {r['session']: r for r in json.load(f)}
    agg = collections.defaultdict(lambda: {'n': 0, 'rating': 0.0, 'out': 0, 'talks': 0})
    for lab, k in key.items():
        r = ratings.get(lab)
        if not r:
            continue
        a = agg[k['source']]
        a['n'] += 1; a['rating'] += float(r['rating']); a['out'] += len(r.get('out_of_place') or []); a['talks'] += k['talks']
    lines = ['| Sort | Sessions rated | Mean rating (1-5) | Out-of-place talks per 10 talks | Talks per session |', '| --- | --- | --- | --- | --- |']
    for src in sorted(agg, key=lambda s: (s != 'claude', s == 'human', s)):
        a = agg[src]
        if a['n']:
            lines.append(f"| {src} | {a['n']} | {a['rating'] / a['n']:.2f} | {10 * a['out'] / a['talks']:.2f} | {a['talks'] / a['n']:.1f} |")
    print('\n'.join(lines))
    write_scores(data_dir, lines, 'Blind judge')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['metrics', 'judge-prepare', 'judge-report'])
    ap.add_argument('data_dir')
    ap.add_argument('--state'); ap.add_argument('--name')
    ap.add_argument('--n', type=int, default=30); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--compare', action='append', default=[], help='judge-prepare: NAME=GITREV or NAME=state:PATH, another sort to sample')
    a = ap.parse_args()
    if a.cmd == 'metrics':
        metrics(a.data_dir, a.state, a.name)
    elif a.cmd == 'judge-prepare':
        judge_prepare(a.data_dir, a.n, a.seed, a.compare)
    else:
        judge_report(a.data_dir)


if __name__ == '__main__':
    main()
