"""Stage 8: scheduling. Room sizes against the rooms we have, then sessions into room-time slots.

    python -m dqi_sort.schedule budget DATA_DIR [--apply]
    python -m dqi_sort.schedule solve  DATA_DIR [--iters 400000] [--seed 1]

budget  decides each in-person session's room size class against the rooms the grid has, length by length: the
        sessions with the highest estimated attendance (the attendance model) get the largest rooms, so each class
        holds exactly as many sessions as it has slots of that length. A size a reviewer set in an area sheet
        (sorting/sessions.csv `size`) is kept. Writes views/room_sizes.md: per length and class the sessions wanted
        and the slots there are, every session whose size differs from its suggestion, and the sessions at each
        boundary, so the lead can swap a few. --apply writes the sizes into sorting/sessions.csv.
solve   assigns every session to a room-time slot (schedule/slots.csv) and writes schedule/schedule.csv and
        views/schedule.md. Hard rules: a slot of the session's own length, in a room of its decided size; no speaker
        in two sessions at once; locked rows in schedule.csv stay. Preferences (weights in config.yaml
        `scheduling_weights`, defaults in WEIGHTS): submitters' day requests (parsed from the cards' constraints;
        "not Friday" is strong, "prefers" weaker); similar sessions not in parallel (session centroids of the card
        embeddings), near-duplicates above all; high-interest sessions spread evenly over the time blocks; each
        room keeping a coherent identity (similar sessions follow each other in a room) without one area filling
        a room for more than a few sessions in a row. Simulated annealing over swaps of sessions with the same length
        and size. Virtual sessions go to virtual slots in a window all their speakers can make.
"""
import argparse, collections, json, math, os, random, re, sys
import numpy as np
from dqi_sort import sessions as S

ORDER = ['large', 'medium', 'small']


def allocate(sess, interest, have):
    """{session_id: size}: per length, reviewers' sizes stand; the rest fill the classes largest first, by interest."""
    decided = {}
    for minutes in {int(s['minutes']) for s in sess}:
        mine = [s for s in sess if int(s['minutes']) == minutes]
        free = collections.Counter({c: have[(c, minutes)] for c in ORDER})
        for s in mine:
            if s.get('size') in ORDER:
                decided[s['session_id']] = s['size']; free[s['size']] -= 1
        rest = sorted((s for s in mine if s['session_id'] not in decided), key=lambda s: -interest[s['session_id']])
        k = 0
        for c in ORDER:
            for s in rest[k:k + max(0, free[c])]:
                decided[s['session_id']] = c
            k += max(0, free[c])
        for s in rest[k:]:                          # more sessions than slots: should not happen after the global pass
            decided[s['session_id']] = 'small'
    return decided


def budget(data_dir, apply=False):
    cfg = S.load_config(data_dir)
    rows = S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))
    sess = [s for s in rows if s['area'] != 'VIRTUAL']
    est = S.estimates(data_dir, sess, cfg)
    if not est:
        sys.exit('no attendance estimates: start Ollama (needed for the model)')
    rooms = {r['room_id']: r for r in S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    slots = [s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv')) if s['track'] == 'in_person']
    have = collections.Counter((rooms[s['room_id']]['size'], int(s['minutes'])) for s in slots)
    decided, lines = allocate(sess, {i: e['interest'] for i, e in est.items()}, have), []
    for minutes in sorted({int(s['minutes']) for s in sess}, reverse=True):
        mine = [s for s in sess if int(s['minutes']) == minutes]
        want = collections.Counter(est[s['session_id']]['size'] for s in mine)
        got = collections.Counter(decided[s['session_id']] for s in mine)
        lines += [f'## {minutes}-minute sessions ({len(mine)})', '', '| Size | Suggested by the model | Slots | Decided |', '| --- | --- | --- | --- |']
        lines += [f'| {c} | {want[c]} | {have[(c, minutes)]} | {got[c]} |' for c in ORDER]
        ranked = sorted(mine, key=lambda s: -est[s['session_id']]['interest'])
        lines += ['', 'At each boundary (the last two in the class above and the first two below; swap any you like):', '']
        for upper, lower in (('large', 'medium'), ('medium', 'small')):
            a = [s for s in ranked if decided[s['session_id']] == upper][-2:]
            b = [s for s in ranked if decided[s['session_id']] == lower][:2]
            lines += [f"- {upper} / {lower}: " + '; '.join(f"{s['session_id']} {s['title'][:45]} (est. {est[s['session_id']]['interest']}, {decided[s['session_id']]})" for s in a + b)]
        lines.append('')
    changed = [s for s in sess if decided[s['session_id']] != est[s['session_id']]['size']]
    up = [s for s in changed if ORDER.index(decided[s['session_id']]) < ORDER.index(est[s['session_id']]['size'])]
    head = ['# Room sizes against the rooms we have', '', 'Generated by `python -m dqi_sort.schedule budget`; do not edit. Within each session length, the sessions '
            'with the highest estimated peak attendance get the largest rooms; sizes reviewers set are kept.', '',
            f'{len(changed)} sessions differ from the model\'s per-session suggestion: {len(up)} move up, {len(changed) - len(up)} move down.', '']
    with open(os.path.join(data_dir, 'views', 'room_sizes.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(head + lines) + '\n')
    print('\n'.join(head + lines))
    if apply:
        for s in rows:
            if s['session_id'] in decided:
                s['size'] = decided[s['session_id']]
        S.write_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'), list(rows[0].keys()), rows)
        print('sizes written to sorting/sessions.csv')
    return decided


DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
WEIGHTS = {'speaker': 1000, 'day_not': 60, 'day_prefer': 15, 'parallel': 400, 'near_duplicate': 80, 'spread': 0.5,
           'room_flow': 300, 'same_area': 15, 'run': 30, 'max_run': 3}
NEG = re.compile(r"\b(not|no|avoid|cannot|can't|unavailable|travel\w*|leav\w*|depart\w*|return\w*|except)\b", re.I)
POS = re.compile(r'\b(prefer\w*|ideally|only|must|available|early|best)\b', re.I)
DAYW = re.compile(r'\b(mon|tue|wed|thu|fri)[a-z]*\b', re.I)


def day_request(text):
    """(forbidden days, preferred days) read from a card's constraints text."""
    bad, good = set(), set()
    for seg in re.split(r'[;.]', text or ''):
        seg = re.sub(r'\b(mon|tue|wed|thu|fri)[a-z]*\s*(?:to|through|-|–)\s*(mon|tue|wed|thu|fri)[a-z]*\b',
                     lambda m: ' '.join(DAYS[DAYS.index(m.group(1)[:3].title()):DAYS.index(m.group(2)[:3].title()) + 1]), seg, flags=re.I)
        days = {d.group(1)[:3].title() for d in DAYW.finditer(seg)}
        if not days and re.search(r'as early as possible', seg, re.I):
            days = {'Mon', 'Tue'}
        if not days:
            continue
        if NEG.search(seg):
            bad |= days
        elif POS.search(seg) or re.search(r'as early as possible', seg, re.I):
            good |= days
    return bad, good - bad


def solve(data_dir, iters=400000, seed=1):
    from dqi_sort.pack import Space
    cfg = S.load_config(data_dir)
    w = dict(WEIGHTS, **(cfg.get('scheduling_weights') or {}))
    rows = S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv')) if t['status'] == 'active'}
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    members = collections.defaultdict(list)
    for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv')):
        if a['session_id'] and a['talk_id'] in talks:
            members[a['session_id']].append(a['talk_id'])
    rooms = {r['room_id']: r for r in S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    slots = {s['slot_id']: s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
    spath = os.path.join(data_dir, 'schedule', 'schedule.csv')
    locked = {r['session_id']: r['slot_id'] for r in (S.read_csv(spath) if os.path.exists(spath) else []) if r.get('locked') == 'true'}
    inp = [s for s in rows if s['area'] != 'VIRTUAL']
    if any(not s['size'] for s in inp):
        sys.exit('some sessions have no room size: run `schedule budget --apply` first')
    est = {k: v['interest'] for k, v in S.estimates(data_dir, inp, cfg).items()}
    ids = [s['session_id'] for s in inp]
    sess = {s['session_id']: s for s in rows}
    # similarity of session centroids
    space = Space(data_dir, talks)
    C = np.array([space.centroid(members[i]) for i in ids]); C /= np.linalg.norm(C, axis=1, keepdims=True)
    sim = C @ C.T
    off = sim[~np.eye(len(ids), dtype=bool)]
    t0, tdup = np.percentile(off, 90), np.percentile(off, 99.5)
    pen = np.maximum(0, sim - t0) * w['parallel'] + (sim >= tdup) * w['near_duplicate']
    flow = (sim - np.median(off)) * w['room_flow']          # neighbours in a room: closer than a typical pair is better
    np.fill_diagonal(pen, 0)
    k = {i: n for n, i in enumerate(ids)}
    speakers = {i: {talks[t]['speaker'].strip().lower() for t in members[i] if talks[t]['speaker'].strip()} for i in ids}
    req = {}
    for i in ids:
        bad, good = collections.Counter(), collections.Counter()
        for t in members[i]:
            b, g = day_request((cards.get(t) or {}).get('constraints'))
            bad.update(b); good.update(g)
        req[i] = (bad, good, sum(1 for t in members[i] if day_request((cards.get(t) or {}).get('constraints'))[1]))
    # slots by class; blocks are (day, start)
    cls = lambda s: (int(s['minutes']), s['size'])
    by_class = collections.defaultdict(list)
    for sl in slots.values():
        if sl['track'] == 'in_person':
            by_class[(int(sl['minutes']), rooms[sl['room_id']]['size'])].append(sl['slot_id'])
    rnd = random.Random(seed)
    assign = dict(locked)
    for c, sids in by_class.items():
        free = [x for x in sids if x not in assign.values()]
        todo = [i for i in ids if cls(sess[i]) == c and i not in assign]
        if len(todo) > len(free):
            sys.exit(f'{len(todo)} sessions of {c} for {len(free)} slots')
        rnd.shuffle(free)
        assign.update(zip(todo, free))
    block = lambda i: (slots[assign[i]]['day'], slots[assign[i]]['start'])
    order = {(d, st): n for n, (d, st) in enumerate(sorted({(sl['day'], sl['start']) for sl in slots.values() if sl['track'] == 'in_person'},
                                                          key=lambda x: (DAYS.index(x[0]), x[1])))}

    def block_cost(members_b):
        cost = 0.0
        for a in range(len(members_b)):
            for b in range(a + 1, len(members_b)):
                cost += pen[k[members_b[a]], k[members_b[b]]]
        sp = collections.Counter(x for i in members_b for x in speakers[i])
        cost += w['speaker'] * sum(c - 1 for c in sp.values() if c > 1)
        return cost

    def day_cost(i):
        d = slots[assign[i]]['day']
        bad, good, n_pref = req[i]
        return w['day_not'] * bad[d] + (w['day_prefer'] * (n_pref - good[d]) if n_pref and d not in good else 0)

    def room_cost(seq):                      # one room's sessions in time order
        cost, run = 0.0, 1
        for a, b in zip(seq, seq[1:]):
            same_day = slots[assign[a]]['day'] == slots[assign[b]]['day']
            if same_day:
                cost -= flow[k[a], k[b]]
                run = run + 1 if sess[a]['area'] == sess[b]['area'] else 1
                cost += w['run'] if run > w['max_run'] else (-w['same_area'] if run > 1 else 0)
            else:
                run = 1
        return cost

    def blocks():
        out = collections.defaultdict(list)
        for i in ids:
            out[block(i)].append(i)
        return out

    def rooms_seq():
        out = collections.defaultdict(list)
        for i in ids:
            out[slots[assign[i]]['room_id']].append(i)
        for r in out:
            out[r].sort(key=lambda i: order[block(i)])
        return out

    def spread(bl):
        means = [np.mean([est[i] for i in v]) for v in bl.values()]
        return w['spread'] * float(np.var(means)) * len(means)

    def total():
        bl, rs = blocks(), rooms_seq()
        return (sum(block_cost(v) for v in bl.values()) + sum(day_cost(i) for i in ids) + sum(room_cost(v) for v in rs.values())
                + spread(bl))

    cur = total()
    movable = collections.defaultdict(list)
    for i in ids:
        if i not in locked:
            movable[cls(sess[i])].append(i)
    classes = [c for c in movable if len(movable[c]) > 1]
    T0 = 30.0
    bl, rs = blocks(), rooms_seq()
    for it in range(iters):
        c = rnd.choice(classes)
        a, b = rnd.sample(movable[c], 2)
        ba, bb = block(a), block(b)
        if ba == bb:
            continue
        ra, rb = slots[assign[a]]['room_id'], slots[assign[b]]['room_id']
        old = block_cost(bl[ba]) + block_cost(bl[bb]) + day_cost(a) + day_cost(b) + room_cost(rs[ra]) + (room_cost(rs[rb]) if rb != ra else 0) + spread(bl)
        assign[a], assign[b] = assign[b], assign[a]
        bl[ba].remove(a); bl[bb].remove(b); bl[ba].append(b); bl[bb].append(a)
        for r in {ra, rb}:
            rs[r].sort(key=lambda i: order[block(i)])
        if ra != rb:
            rs[ra][rs[ra].index(a)] = b; rs[rb][rs[rb].index(b)] = a
            for r in (ra, rb):
                rs[r].sort(key=lambda i: order[block(i)])
        new = block_cost(bl[ba]) + block_cost(bl[bb]) + day_cost(a) + day_cost(b) + room_cost(rs[ra]) + (room_cost(rs[rb]) if rb != ra else 0) + spread(bl)
        T = T0 * (1 - it / iters) + 0.05
        if new <= old or rnd.random() < math.exp((old - new) / T):
            cur += new - old
        else:                                 # undo
            assign[a], assign[b] = assign[b], assign[a]
            bl[ba].remove(b); bl[bb].remove(a); bl[ba].append(a); bl[bb].append(b)
            if ra != rb:
                rs[ra][rs[ra].index(b)] = a; rs[rb][rs[rb].index(a)] = b
            for r in {ra, rb}:
                rs[r].sort(key=lambda i: order[block(i)])
    # virtual sessions: a slot in a window every speaker can make
    vres = virtual_slots(data_dir, rows, members, talks, slots)
    assign.update(vres)
    out = [{'session_id': i, 'slot_id': assign[i], 'locked': 'true' if i in locked else 'false'} for i in sorted(assign)]
    S.write_csv(spath, ['session_id', 'slot_id', 'locked'], out)
    report(data_dir, sess, assign, slots, rooms, members, talks, cards, sim, k, tdup, t0, est, req, speakers, blocks(), rooms_seq(), w)
    return assign


def virtual_slots(data_dir, rows, members, talks, slots):
    win = lambda txt: {m.group(0)[:5] for m in re.finditer(r'\d\d:\d\d-\d\d:\d\d', txt or '')}
    assumed = {}
    p = os.path.join(data_dir, 'work', 'sessions', 'VIRTUAL', 'proposal.json')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            assumed = {i: {w[:5] for w in re.findall(r'\d\d:\d\d-\d\d:\d\d', v if isinstance(v, str) else ' '.join(v))}
                       for i, v in (json.load(f).get('assumed_windows') or {}).items()}
    free = sorted((s for s in slots.values() if s['track'] == 'virtual'), key=lambda s: (s['start'], DAYS.index(s['day'])))
    used_days, out = collections.Counter(), {}
    for s in sorted((s for s in rows if s['area'] == 'VIRTUAL'), key=lambda s: s['session_id']):
        ok = None
        for t in members[s['session_id']]:
            w_ = assumed.get(t) or win(talks[t]['time_windows'])
            ok = w_ if ok is None else (ok & w_ if w_ else ok)
        cands = [x for x in free if x['slot_id'] not in out.values() and (not ok or x['start'] in ok)]
        if not cands:
            print(f"no virtual slot in a shared window for {s['session_id']}"); continue
        best = min(cands, key=lambda x: (used_days[x['day']], DAYS.index(x['day'])))
        out[s['session_id']] = best['slot_id']; used_days[best['day']] += 1
    return out


def report(data_dir, sess, assign, slots, rooms, members, talks, cards, sim, k, tdup, t0, est, req, speakers, bl, rs, w):
    lines = ['# The schedule (proposed)', '', 'Generated by `python -m dqi_sort.schedule solve`; do not edit. Rows: time blocks; one line per room.', '']
    clashes, dup_par, close_par, day_bad, day_pref = [], [], [], [], []
    for b, v in sorted(bl.items(), key=lambda kv: (DAYS.index(kv[0][0]), kv[0][1])):
        sp = collections.Counter(x for i in v for x in speakers[i])
        clashes += [f'{b[0]} {b[1]}: {x}' for x, c in sp.items() if c > 1]
        for a in range(len(v)):
            for c in range(a + 1, len(v)):
                s_ = sim[k[v[a]], k[v[c]]]
                if s_ >= tdup:
                    dup_par.append(f'{b[0]} {b[1]}: {v[a]} {sess[v[a]]["title"][:40]} / {v[c]} {sess[v[c]]["title"][:40]} ({s_:.3f})')
    for i, (bad, good, n_pref) in req.items():
        d = slots[assign[i]]['day']
        if bad[d]:
            day_bad.append(f"{i} on {d}: {bad[d]} talk(s) asked not to be on {d}")
        if n_pref and d not in good:
            day_pref.append(f"{i} on {d}: preferred " + '/'.join(sorted(good)))
    n_req = sum(1 for i in req if sum(req[i][0].values()) or req[i][2])
    lines += ['## Checks', '',
              f'- Every session has a slot of its own length in a room of its decided size: yes ({len(assign)} sessions).',
              f'- Speakers in two sessions at once: {len(clashes)}' + (': ' + '; '.join(clashes) if clashes else ''),
              f'- Day requests: {n_req} sessions hold a talk with one; {len(day_bad)} "not this day" broken, {len(day_pref)} preferences missed.',
              f'- Near-duplicate sessions in parallel (similarity at least {tdup:.3f}, the top 0.5% of pairs): {len(dup_par)}.', '']
    if day_bad or day_pref:
        lines += ['### Day requests not met', ''] + [f'- {x}' for x in day_bad + day_pref] + ['']
    if dup_par:
        lines += ['### Near-duplicates in parallel', ''] + [f'- {x}' for x in dup_par] + ['']
    means = {b: np.mean([est[i] for i in v]) for b, v in bl.items()}
    lines += ['## The grid', '']
    room_order = sorted(rooms, key=lambda r: (['large', 'medium', 'small'].index(rooms[r]['size']), r))
    for b in sorted(bl, key=lambda x: (DAYS.index(x[0]), x[1])):
        lines += [f'### {b[0]} {b[1]} (mean estimated peak {means[b]:.0f})', '']
        here = {slots[assign[i]]['room_id']: i for i in bl[b]}
        for r in room_order:
            if r in here:
                i = here[r]
                lines.append(f"- {r} ({rooms[r]['size']}): {i} {sess[i]['title']} (est. {est[i]})")
        lines.append('')
    v = [i for i in assign if sess[i]['area'] == 'VIRTUAL']
    if v:
        lines += ['## Virtual', ''] + [f"- {slots[assign[i]]['day']} {slots[assign[i]]['start']}: {i} {sess[i]['title']}" for i in sorted(v)] + ['']
    lines += ['## Day requests as read from the cards (check the reading)', '']
    for i, (bad, good, n_pref) in sorted(req.items()):
        if sum(bad.values()) or n_pref:
            lines.append(f"- {i} ({slots[assign[i]]['day']}): " + ', '.join(f'not {d} x{c}' for d, c in bad.items())
                         + (f"; prefers {'/'.join(sorted(good))}" if n_pref else ''))
    with open(os.path.join(data_dir, 'views', 'schedule.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:14]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['budget', 'solve'])
    ap.add_argument('data_dir')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--iters', type=int, default=400000)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    if a.cmd == 'budget':
        budget(a.data_dir, a.apply)
    else:
        solve(a.data_dir, a.iters, a.seed)


if __name__ == '__main__':
    main()
