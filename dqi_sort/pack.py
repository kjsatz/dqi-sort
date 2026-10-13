"""Stage 6: the global pass (packing). Fit the whole sort to the session slots in one view.

    python -m dqi_sort.pack start DATA_DIR [--restart]
    python -m dqi_sort.pack ops DATA_DIR OPS.json
    python -m dqi_sort.pack status DATA_DIR
    python -m dqi_sort.pack critique DATA_DIR
    python -m dqi_sort.pack finish DATA_DIR [--replace] [--no-attendance]

start     collects the stage 5 drafts (work/sessions/*/proposal.json) into work/pack/state.json: the in-person draft
          sessions and the pool of released talks. The virtual sessions are carried through unchanged: the virtual
          track is final after its draft, and no talk ever moves between the virtual and in-person tracks. It writes the
          files the global agent works from (work/pack/): overview.md (every session and its talks; full cards for the
          pool), check.md (the length check), candidates.md (short lists from the card embeddings), prompt.md.
ops       applies a list of moves (JSON; see OPS below) atomically, records them in work/pack/log.jsonl with their
          reasons, rewrites the working files and prints the length check. Nothing is applied if any op is invalid.
status    prints the length check.
critique  writes one folder per review area (work/pack/critique/AREA/) for an independent critic: the area's sessions
          with full cards, every session title in DQI, and prompt.md. Critics write suggestions.json; the global agent
          then weighs them in a second round of ops.
finish    requires the sort to fit, picks each session's length, assigns review areas (by content: the area that
          most of a session's talks' card categories belong to), and writes sorting/sessions.csv, sorting/assignments.csv, sorting/moves.csv,
          views/sessions.md, views/sessions/AREA.md and views/packing_report.md (the pull request description). Talks
          held for the lead go to sorting/held.csv and views/flags.md (dqi_sort.areas), the one list of talks the
          lead must decide.

OPS: a JSON list of objects, each with a one-line "reason" (it goes into the packing report):
    {"op": "move", "talk": ID, "to": SESSION or "pool", "position": N (optional, 1-based), "reason": ...}
    {"op": "new", "title": ..., "scope": ..., "talks": [IDs in order], "reason": ...}     new session, ID X01, X02...
    {"op": "dissolve", "session": SESSION, "reason": ...}                                 its talks go to the pool
    {"op": "edit", "session": SESSION, "title": ... and/or "scope": ..., "reason": ...}
    {"op": "order", "session": SESSION, "talks": [the same IDs in a new order], "reason": ...}
    {"op": "hold", "talk": ID, "action": "poster" | "other_unit" | "decide", "unit": UNIT (for other_unit), "reason": ...}
        leave a pool talk out of every session for the lead, with a proposal: a poster (no scientific
        content), another APS unit, or no proposal (no good home in DQI; the lead decides)
Moving any part of a series moves the whole series, in order.

The length check: a 144-minute session holds 12 units (11 allowed), a 108-minute session 9 (8 allowed); an oral talk
is 1 unit, an invited talk 3. Given the number of slots of each length, it picks the lengths that need the fewest
talk moves and lists each session that must grow or shrink. The sort fits when no session needs a change, there
are no more sessions than slots, and the pool is empty (talks may stay in the pool only with a reason, for the lead).
"""
import argparse, collections, datetime, glob, json, os, sys
import numpy as np
from dqi_sort import areas as A, sessions as S
from dqi_sort.embed import load as load_embeddings

LENGTHS = {144: (11, 12), 108: (8, 9)}     # minutes: (fewest units allowed, most)
HOLD_ACTIONS = ('poster', 'other_unit', 'decide')
NEAR = 5


def wdir(data_dir):
    return os.path.join(data_dir, 'work', 'pack')


# ---------- state ----------
class Sort:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.cfg = S.load_config(data_dir)
        rows = S.read_csv(os.path.join(data_dir, 'talks.csv'))
        self.talks = {t['talk_id']: t for t in rows if t['status'] == 'active'}
        with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
            self.cards = {c['talk_id']: c for c in map(json.loads, f) if c}
        self.n144, self.n108, _, _ = S.grid(data_dir)
        self.path = os.path.join(wdir(data_dir), 'state.json')
        self.state = None
        self.parts = collections.defaultdict(list)
        for i, t in self.talks.items():
            if t['series']:
                self.parts[t['series']].append(i)
        for v in self.parts.values():
            v.sort(key=lambda i: int(self.talks[i]['series_part']))

    def load(self):
        with open(self.path, encoding='utf-8') as f:
            self.state = json.load(f)
        return self

    def save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)

    def units(self, ids):
        return sum(S.units(self.talks[i]) for i in ids)

    def session(self, sid):
        return next((s for s in self.state['sessions'] if s['id'] == sid), None)

    def where(self, i):
        for s in self.state['sessions']:
            if i in s['talks']:
                return s['id']
        return 'pool' if any(p['id'] == i for p in self.state['pool']) else None

    def block(self, i):
        t = self.talks[i]
        return list(self.parts[t['series']]) if t['series'] else [i]

    def remove(self, ids):
        for s in self.state['sessions']:
            s['talks'] = [i for i in s['talks'] if i not in ids]
        self.state['pool'] = [p for p in self.state['pool'] if p['id'] not in ids]


def start(data_dir, restart=False):
    srt = Sort(data_dir)
    os.makedirs(wdir(data_dir), exist_ok=True)
    if os.path.exists(srt.path) and not restart:
        sys.exit(f'{srt.path} exists; pass --restart to start the global pass again from the drafts')
    sessions, pool, virtual = [], [], []
    for path in sorted(glob.glob(os.path.join(data_dir, 'work', 'sessions', '*', 'proposal.json'))):
        p, data = S.load_area(path)
        err, _ = S.check_proposal(p, data)
        area = data['limits']['area']
        if err:
            sys.exit(f'{area}: draft has {len(err)} errors; run sessions check')
        for k, s in enumerate(p['sessions'], 1):
            rec = {'id': f'{area}{k:02d}', 'title': s['title'].strip(), 'scope': s.get('scope', '').strip(), 'area': area,
                   'talks': list(s['talks'])}
            (virtual if data['limits']['virtual'] else sessions).append(dict(rec, minutes=s.get('minutes')) if data['limits']['virtual'] else rec)
        for r in p.get('released') or []:
            rec = {'id': r['id'], 'from': area, 'reason': r['reason'].strip(), 'suggested_home': r['suggested_home'].strip()}
            pool.append(rec)                         # the check refuses releases from the virtual draft
    srt.state = {'sessions': sessions, 'pool': pool, 'virtual': virtual, 'next_new': 1, 'round': 1}
    srt.save()
    with open(os.path.join(wdir(data_dir), 'log.jsonl'), 'w', encoding='utf-8'):
        pass
    write_files(srt)
    print(f'{len(sessions)} draft sessions, {len(pool)} talks in the pool, {len(virtual)} virtual sessions')
    print(status_text(srt))


# ---------- ops ----------
def apply_ops(srt, ops):
    """Apply ops in order to srt.state; returns (log entries, errors). The caller saves only if there are no errors."""
    log, err = [], []
    for k, o in enumerate(ops, 1):
        kind, reason = o.get('op'), str(o.get('reason', '')).strip()
        if not reason:
            err.append(f'op {k}: needs a reason'); continue
        if kind == 'move':
            i, to = o.get('talk'), o.get('to')
            if i not in srt.talks or srt.where(i) is None:
                err.append(f'op {k}: {i!r} is not an active in-person talk in the sort'); continue
            if to != 'pool' and not srt.session(to):
                err.append(f'op {k}: no session {to!r}'); continue
            if to != 'pool' and srt.talks[i]['track'] == 'virtual':
                err.append(f'op {k}: {i} is a virtual talk; it cannot go into an in-person session'); continue
            blk = srt.block(i)
            frm = srt.where(i)
            srt.remove(set(blk))
            if to == 'pool':
                srt.state['pool'] += [{'id': j, 'from': frm, 'reason': reason, 'suggested_home': ''} for j in blk]
            else:
                tl = srt.session(to)['talks']
                pos = o.get('position')
                pos = len(tl) if not isinstance(pos, int) else max(0, min(len(tl), pos - 1))
                tl[pos:pos] = blk
            log += [{'op': 'move', 'talk': j, 'from': frm, 'to': to, 'reason': reason} for j in blk]
        elif kind == 'new':
            ids = o.get('talks') or []
            bad = [i for i in ids if i not in srt.talks or srt.where(i) is None or srt.talks[i]['track'] == 'virtual']
            if not ids or bad or not str(o.get('title', '')).strip():
                err.append(f'op {k}: new session needs a title and talks in the sort (bad: {bad})'); continue
            sid = f"X{srt.state['next_new']:02d}"
            srt.state['next_new'] += 1
            order = []
            for i in ids:
                for j in srt.block(i):
                    if j not in order:
                        order.append(j)
            frm = {j: srt.where(j) for j in order}
            srt.remove(set(order))
            srt.state['sessions'].append({'id': sid, 'title': o['title'].strip(), 'scope': str(o.get('scope', '')).strip(),
                                          'area': '', 'talks': order})
            log.append({'op': 'new', 'session': sid, 'title': o['title'].strip(), 'reason': reason})
            log += [{'op': 'move', 'talk': j, 'from': frm[j], 'to': sid, 'reason': reason} for j in order]
        elif kind == 'dissolve':
            s = srt.session(o.get('session'))
            if not s:
                err.append(f"op {k}: no session {o.get('session')!r}"); continue
            srt.state['pool'] += [{'id': j, 'from': s['id'], 'reason': reason, 'suggested_home': ''} for j in s['talks']]
            log.append({'op': 'dissolve', 'session': s['id'], 'title': s['title'], 'reason': reason})
            log += [{'op': 'move', 'talk': j, 'from': s['id'], 'to': 'pool', 'reason': reason} for j in s['talks']]
            srt.state['sessions'].remove(s)
        elif kind == 'edit':
            s = srt.session(o.get('session'))
            if not s or not (o.get('title') or o.get('scope')):
                err.append(f'op {k}: edit needs a session and a title or scope'); continue
            for f in ('title', 'scope'):
                if o.get(f):
                    s[f] = str(o[f]).strip()
            log.append({'op': 'edit', 'session': s['id'], 'title': s['title'], 'reason': reason})
        elif kind == 'order':
            s = srt.session(o.get('session'))
            if not s or sorted(o.get('talks') or []) != sorted(s['talks']):
                err.append(f'op {k}: order must list exactly the talks of the session'); continue
            s['talks'] = list(o['talks'])
            log.append({'op': 'order', 'session': s['id'], 'reason': reason})
        elif kind == 'hold':
            p = next((p for p in srt.state['pool'] if p['id'] == o.get('talk')), None)
            if not p:
                err.append(f"op {k}: {o.get('talk')!r} is not in the pool"); continue
            if 'lead_kept' in (srt.talks[p['id']].get('flags') or ''):
                err.append(f"op {k}: the lead kept {p['id']} in DQI; place it in a session"); continue
            act, unit = o.get('action'), str(o.get('unit') or '').strip()
            if act not in HOLD_ACTIONS:
                err.append(f"op {k}: hold needs an action: one of {', '.join(HOLD_ACTIONS)}"); continue
            if act == 'other_unit' and not unit:
                err.append(f'op {k}: hold with action other_unit needs the unit'); continue
            p.update(hold=True, reason=reason, action=act, unit=unit if act == 'other_unit' else '')
            log.append({'op': 'hold', 'talk': p['id'], 'action': act, 'unit': p['unit'], 'reason': reason})
        else:
            err.append(f'op {k}: unknown op {kind!r}')
    for s in srt.state['sessions']:
        if not s['talks']:
            log.append({'op': 'dissolve', 'session': s['id'], 'title': s['title'], 'reason': 'emptied'})
    srt.state['sessions'] = [s for s in srt.state['sessions'] if s['talks']]
    return log, err


def ops(data_dir, path):
    srt = Sort(data_dir).load()
    with open(path, encoding='utf-8') as f:
        todo = json.load(f)
    log, err = apply_ops(srt, todo if isinstance(todo, list) else [todo])
    if err:
        print('\n'.join('ERROR ' + e for e in err))
        sys.exit(f'{len(err)} invalid ops; nothing applied')
    srt.save()
    rnd = srt.state.get('round', 1)
    with open(os.path.join(wdir(data_dir), 'log.jsonl'), 'a', encoding='utf-8') as f:
        for e in log:
            f.write(json.dumps(dict(e, round=rnd), ensure_ascii=False) + '\n')
    write_files(srt)
    print(f'applied {len(todo)} ops')
    print(status_text(srt))


# ---------- the length check ----------
def cost(u, minutes):
    lo, hi = LENGTHS[minutes]
    return max(0, lo - u) + max(0, u - hi)


def choose_lengths(units, n144, n108):
    """{session id: minutes} needing the fewest talk moves, with at most n144 and n108 of each. units: {sid: units}."""
    ids = list(units)
    n = len(ids)
    d = sorted(ids, key=lambda i: cost(units[i], 144) - cost(units[i], 108))
    lo, hi = max(0, n - n108), min(n144, n)
    if lo > hi:                                  # more sessions than slots: best lengths ignoring the counts
        return {i: 144 if cost(units[i], 144) <= cost(units[i], 108) else 108 for i in ids}
    best = None
    for k in range(lo, hi + 1):
        c = sum(cost(units[i], 144) for i in d[:k]) + sum(cost(units[i], 108) for i in d[k:])
        if best is None or c < best[0]:
            best = (c, k)
    k = best[1]
    return {i: (144 if r < k else 108) for r, i in enumerate(d)}


def problems(srt):
    """Rule problems (errors) and soft warnings in the current sort."""
    err, warn = [], []
    inst_max = srt.cfg.get('max_same_institution', 4)
    apart = S.apart_pairs(srt.data_dir) if getattr(srt, 'data_dir', None) else {}
    for s in srt.state['sessions']:
        info = {i: {'type': srt.talks[i]['type'], 'units': S.units(srt.talks[i]), 'series': srt.talks[i]['series'],
                    'part': int(srt.talks[i]['series_part'] or 0), 'institution': srt.talks[i]['institution'] or srt.talks[i]['affiliation'],
                    'windows': [], 'apart': sorted(apart.get(i, ()))} for i in s['talks']}
        lim = {'virtual': False, 'minutes': [144, 108], 'max_same_institution': inst_max}
        e, w = S.session_problems(dict(s, minutes=None), s['id'], info, lim, {})
        err += [x for x in e if 'units' not in x]
        warn += w
        err += [f"{s['id']}: {i} is a virtual talk in an in-person session" for i in s['talks'] if srt.talks[i]['track'] != 'in_person']
    for s in srt.state.get('virtual', []):          # the tracks are a hard partition
        err += [f"{s['id']}: {i} is an in-person talk in a virtual session" for i in s['talks'] if srt.talks[i]['track'] != 'virtual']
    err += [f"pool: {p['id']} is a virtual talk; it belongs in a virtual session" for p in srt.state['pool'] if srt.talks[p['id']]['track'] != 'in_person']
    return err, warn


def check(srt):
    units = {s['id']: srt.units(s['talks']) for s in srt.state['sessions']}
    lengths = choose_lengths(units, srt.n144, srt.n108)
    delta = {}
    for sid, u in units.items():
        lo, hi = LENGTHS[lengths[sid]]
        delta[sid] = lo - u if u < lo else (hi - u if u > hi else 0)
    err, warn = problems(srt)
    extra = len(units) - (srt.n144 + srt.n108)
    held = [p for p in srt.state['pool'] if p.get('hold')]
    fits = not err and extra <= 0 and all(v == 0 for v in delta.values()) and len(held) == len(srt.state['pool'])
    return {'units': units, 'lengths': lengths, 'delta': delta, 'errors': err, 'warnings': warn, 'extra_sessions': extra, 'fits': fits}


def status_text(srt, c=None):
    c = c or check(srt)
    L = collections.Counter(c['lengths'].values())
    grow = {k: v for k, v in c['delta'].items() if v > 0}
    shrink = {k: v for k, v in c['delta'].items() if v < 0}
    pool_units = srt.units([p['id'] for p in srt.state['pool']])
    cap = sum(LENGTHS[m][1] for m in c['lengths'].values())
    lines = [f"Round {srt.state.get('round', 1)}. {'FITS' if c['fits'] else 'DOES NOT FIT YET'}: {len(c['units'])} sessions ({L[144]} x 144, {L[108]} x 108) "
             f"against {srt.n144} x 144 + {srt.n108} x 108 slots; {sum(c['units'].values())} units in sessions, "
             f"{len(srt.state['pool'])} talks ({pool_units} units) in the pool; capacity of these sessions {cap} units"]
    if c['extra_sessions'] > 0:
        lines.append(f"- {c['extra_sessions']} sessions more than slots: merge or dissolve some")
    elif c['extra_sessions'] < 0:
        lines.append(f"- {-c['extra_sessions']} slots unused ({srt.n144 - L[144]} x 144, {srt.n108 - L[108]} x 108 free)")
    if grow:
        lines.append(f"- {len(grow)} sessions must grow ({sum(grow.values())} units): " + ', '.join(f'{k} +{v}' for k, v in sorted(grow.items())))
    if shrink:
        lines.append(f"- {len(shrink)} sessions must shrink ({-sum(shrink.values())} units): " + ', '.join(f'{k} {v}' for k, v in sorted(shrink.items())))
    lines += ['- ERROR ' + e for e in c['errors']] + ['- WARN ' + w for w in c['warnings']]
    return '\n'.join(lines)


# ---------- embeddings: candidates and coherence ----------
class Space:
    def __init__(self, data_dir, talk_ids):
        ids, X, _ = load_embeddings(os.path.join(data_dir, 'embeddings', 'cards.npz'))
        self.row = {i: k for k, i in enumerate(ids)}
        self.X = X.astype(float)

    def vec(self, i):
        k = self.row.get(i)
        return self.X[k] if k is not None else None

    def centroid(self, ids, leave_out=None):
        v = [self.vec(i) for i in ids if i != leave_out and self.vec(i) is not None]
        if not v:
            return None
        c = np.mean(v, axis=0)
        return c / (np.linalg.norm(c) or 1)


def coherence(space, ids):
    """Mean similarity of each talk to the rest of its session (leave-one-out centroid); and per-talk values."""
    per = {}
    for i in ids:
        c, v = space.centroid(ids, leave_out=i), space.vec(i)
        if c is not None and v is not None:
            per[i] = float(v @ c)
    return (float(np.mean(list(per.values()))) if per else 0.0), per


def candidates_text(srt, c, space):
    sess = srt.state['sessions']
    cent = {s['id']: space.centroid(s['talks']) for s in sess}
    title = {s['id']: s['title'] for s in sess}
    sids = [s['id'] for s in sess if cent[s['id']] is not None]
    M = np.array([cent[k] for k in sids])

    def tag(k):
        d = c['delta'][k]
        return f"{k} ({c['units'][k]}u, {c['lengths'][k]}{', +' + str(d) if d > 0 else (', ' + str(d) if d < 0 else '')})"
    out = ['# Candidates from the card embeddings', '',
           'Similarity is cosine on EmbeddingGemma card vectors (about 0.85 is unrelated, 0.95 very close). Use these as '
           'pointers, not answers.', '']
    pool = [p['id'] for p in srt.state['pool']]
    if pool:
        out += ['## Pool talks: nearest sessions and nearest other pool talks', '']
        for i in pool:
            v = space.vec(i)
            if v is None:
                continue
            sims = M @ v
            near = [f'{tag(sids[j])} {sims[j]:.3f}' for j in np.argsort(-sims)[:NEAR]]
            pn = sorted(((float(v @ space.vec(q)), q) for q in pool if q != i and space.vec(q) is not None), reverse=True)[:NEAR]
            out.append(f"- {i} {srt.talks[i]['title'][:90]}")
            out.append('  - sessions: ' + '; '.join(near))
            out.append('  - pool: ' + '; '.join(f'{q} {s:.3f}' for s, q in pn))
        out.append('')
    spare = {k: c['units'][k] - LENGTHS[c['lengths'][k]][0] for k in sids}
    grow = [k for k in sids if c['delta'][k] > 0]
    if grow:
        out += ['## Sessions that must grow: nearby sessions with talks to spare, and their talks closest to this one', '']
        for k in grow:
            sims = M @ cent[k]
            out.append(f'- {tag(k)} {title[k][:70]}')
            n = 0
            for j in np.argsort(-sims):
                d = sids[j]
                if d == k or spare[d] <= 0 and c['delta'][d] >= 0:
                    continue
                talks = sorted(((float(space.vec(i) @ cent[k]), i) for i in srt.session(d)['talks'] if space.vec(i) is not None), reverse=True)[:2]
                out.append(f"  - {tag(d)} {title[d][:50]} ({sims[j]:.3f}): " + ', '.join(f'{i} {s:.3f}' for s, i in talks))
                n += 1
                if n == 4:
                    break
        out.append('')
    shrink = [k for k in sids if c['delta'][k] < 0]
    if shrink:
        out += ['## Sessions that must shrink: their talks furthest from the rest, and each one\'s best other session', '']
        for k in shrink:
            _, per = coherence(space, srt.session(k)['talks'])
            out.append(f'- {tag(k)} {title[k][:70]}')
            for i, s in sorted(per.items(), key=lambda kv: kv[1])[:3]:
                sims = M @ space.vec(i)
                alt = [sids[j] for j in np.argsort(-sims) if sids[j] != k][:2]
                out.append(f"  - {i} {s:.3f} {srt.talks[i]['title'][:60]} -> " + ', '.join(tag(a) for a in alt))
        out.append('')
    sug = []
    for f in sorted(glob.glob(os.path.join(wdir(srt.data_dir), 'critique', '*', 'suggestions.json'))):
        with open(f, encoding='utf-8') as fh:
            sug += [x for x in json.load(fh) if x.get('talk') and x.get('to')]
    if sug:
        out += ['## Critic moves with swap partners', '',
                'For each suggested move: where the talk is now, and the talks in the target session that fit that session best. '
                'Swapping one of them back (same units) keeps both lengths, so a suggestion into a full session is still possible.', '']
        for x in sug:
            i, to, frm = x['talk'], x['to'], srt.where(x['talk'])
            if frm in (None, 'pool', to) or not srt.session(to) or cent.get(frm) is None:
                continue
            u = S.units(srt.talks[i])
            back = sorted(((float(space.vec(j) @ cent[frm]), j) for j in srt.session(to)['talks']
                           if space.vec(j) is not None and S.units(srt.talks[j]) == u and not srt.talks[j]['series']), reverse=True)[:3]
            out.append(f"- {i} {tag(frm)} -> {tag(to)}: swap back " + ', '.join(f'{j} {v:.3f} {srt.talks[j]["title"][:40]}' for v, j in back))
        out.append('')
    area_of = {s['id']: s['area'] for s in sess}
    S2 = M @ M.T
    pairs = sorted(((S2[a, b], sids[a], sids[b]) for a in range(len(sids)) for b in range(a + 1, len(sids))
                    if area_of[sids[a]] != area_of[sids[b]]), reverse=True)[:12]
    out += ['## Most similar sessions in different areas (possible duplicates: merge, re-split along a clearer line, '
            'or at least note them so they are not scheduled at the same time)', '']
    out += [f'- {a} {title[a][:55]} | {b} {title[b][:55]} ({v:.3f})' for v, a, b in pairs]
    out.append('')
    coh = sorted((coherence(space, s['talks'])[0], s['id']) for s in sess)
    out += ['## Least coherent sessions (mean similarity of each talk to the rest of its session)', '']
    out += [f'- {k} {v:.3f} {title[k][:80]}' for v, k in coh[:12]]
    return '\n'.join(out) + '\n'


# ---------- working files ----------
def talk_line(srt, i):
    t = srt.talks[i]
    ser = f" | series {t['series']} part {t['series_part']}" if t['series'] else ''
    return f"  {i} | {'INVITED' if t['type'] == 'invited' else 'oral'} | {t['title']} | {t['institution'] or t['affiliation']}{ser}"


def write_files(srt):
    c = check(srt)
    d = wdir(srt.data_dir)
    series_parts = collections.Counter(t['series'] for t in srt.talks.values() if t['series'])
    lines = ['# The sort (global pass working view)', '', status_text(srt, c), '']
    for area in sorted({s['area'] for s in srt.state['sessions']}):
        lines += [f"## {area or 'New sessions'}", '']
        for s in srt.state['sessions']:
            if s['area'] != area:
                continue
            dl = c['delta'][s['id']]
            need = f', +{dl}' if dl > 0 else (f', {dl}' if dl < 0 else '')
            lines.append(f"### {s['id']} ({c['units'][s['id']]} units -> {c['lengths'][s['id']]}{need}): {s['title']}")
            if s['scope']:
                lines.append(f"_{s['scope']}_")
            lines += [talk_line(srt, i) for i in s['talks']] + ['']
    lines += [f"## Pool ({len(srt.state['pool'])} talks)", '']
    for p in srt.state['pool']:
        t = srt.talks[p['id']]
        lines.append(S.card_text(t, srt.cards.get(p['id']), series_parts))
        lines.append(f"  released by {p['from']}: {p['reason']}" + (f" Suggested home: {p['suggested_home']}" if p.get('suggested_home') else ''))
        lines.append('')
    with open(os.path.join(d, 'overview.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    with open(os.path.join(d, 'check.md'), 'w', encoding='utf-8') as f:
        f.write(status_text(srt, c) + '\n')
    space = Space(srt.data_dir, srt.talks)
    with open(os.path.join(d, 'candidates.md'), 'w', encoding='utf-8') as f:
        f.write(candidates_text(srt, c, space))
    with open(os.path.join(S.HERE, 'prompts', 'pack_spec.md'), encoding='utf-8') as f:
        spec = f.read()
    cmd = f'cd {S.HERE} && .venv/bin/python -m dqi_sort.pack'
    with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
        f.write(spec.replace('{DIR}', os.path.abspath(d)).replace('{PACK}', cmd).replace('{DATA}', os.path.abspath(srt.data_dir))
                .replace('{MAX_INST}', str(srt.cfg.get('max_same_institution', 4))))


# ---------- critique ----------
def review_areas(srt):
    """{session id: review area}, by content: the area (config.yaml areas) that most of the session's talks' card
    categories belong to; ties and talks without a card fall back to the area they were drafted in."""
    import re
    from dqi_sort.areas import MODALITY_WORDS
    areas = srt.cfg.get('areas') or {}
    by_cat = {c: a for a, v in areas.items() for c in v.get('categories') or []}
    by_mod = {v['modality']: a for a, v in areas.items() if v.get('modality')}

    def vote(i):
        card = srt.cards.get(i) or {}
        a = by_cat.get(card.get('best_category'), srt.talks[i]['area'])
        mods = [m for m, rx in MODALITY_WORDS.items() if re.search(rx, card.get('platform', ''), re.I)]
        if areas.get(a, {}).get('modality') and len(mods) == 1 and mods[0] != areas[a]['modality'] and mods[0] in by_mod:
            a = by_mod[mods[0]]                          # category says one platform area, the platform says another
        return a
    out = {}
    for s in srt.state['sessions']:
        votes = collections.Counter()
        for i in s['talks']:
            votes[vote(i)] += 1
            votes[srt.talks[i]['area']] += 0.5           # breaks ties toward where the talk was drafted
        out[s['id']] = votes.most_common(1)[0][0]
    return out


def critique(data_dir):
    srt = Sort(data_dir).load()
    ra = review_areas(srt)
    c = check(srt)
    root = os.path.join(wdir(data_dir), 'critique')
    series_parts = collections.Counter(t['series'] for t in srt.talks.values() if t['series'])
    allt = ['# Every session in DQI', ''] + [f"- {s['id']} [{ra[s['id']]}] {s['title']}: {s['scope']}" for s in srt.state['sessions']]
    with open(os.path.join(S.HERE, 'prompts', 'critique_spec.md'), encoding='utf-8') as f:
        spec = f.read()
    for area in sorted(set(ra.values())):
        d = os.path.join(root, area)
        os.makedirs(d, exist_ok=True)
        for f in glob.glob(os.path.join(d, 'suggestions.json')):
            os.rename(f, f + '.old')
        lines = [f'# {area}: sessions to critique', '']
        for s in srt.state['sessions']:
            if ra[s['id']] != area:
                continue
            lines += [f"## {s['id']}: {s['title']} ({c['units'][s['id']]} units, {c['lengths'][s['id']]} min)", f"_{s['scope']}_", '']
            lines += [S.card_text(srt.talks[i], srt.cards.get(i), series_parts) for i in s['talks']] + ['']
        with open(os.path.join(d, 'sessions.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        with open(os.path.join(d, 'all_sessions.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(allt) + '\n')
        with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
            f.write(spec.replace('{DIR}', os.path.abspath(d)).replace('{AREA}', area))
    srt.state['round'] = srt.state.get('round', 1) + 1
    srt.save()
    print(f"critique folders for {len(set(ra.values()))} review areas in {root}; next ops are round {srt.state['round']}")


# ---------- finish ----------
def finish(data_dir, replace=False, attendance=True):
    srt = Sort(data_dir).load()
    c = check(srt)
    if not c['fits']:
        sys.exit('the sort does not fit yet:\n' + status_text(srt, c))
    sort_dir = os.path.join(data_dir, 'sorting')
    if os.path.exists(os.path.join(sort_dir, 'assignments.csv')) and not replace:
        sys.exit('sorting/assignments.csv exists; pass --replace to overwrite the sort')
    ra = review_areas(srt)
    space = Space(data_dir, srt.talks)
    rows, assign = [], {}
    for s in srt.state['sessions']:
        inv = sum(srt.talks[i]['type'] == 'invited' for i in s['talks'])
        coh, per = coherence(space, s['talks'])
        rows.append({'session_id': s['id'], 'title': s['title'], 'kind': S.kind(inv), 'minutes': c['lengths'][s['id']], 'size': '',
                     'area': ra[s['id']], 'locked': 'false', 'scope': s['scope'], 'notes': '', 'talks': s['talks'],
                     'used': srt.units(s['talks']) * S.UNIT_MIN, 'coherence': coh,
                     'weakest': [i for i, _ in sorted(per.items(), key=lambda kv: kv[1])[:2]]})
    for v in srt.state['virtual']:
        rows.append({'session_id': v['id'], 'title': v['title'], 'kind': 'contributed', 'minutes': v['minutes'], 'size': '',
                     'area': 'VIRTUAL', 'locked': 'false', 'scope': v['scope'], 'notes': '', 'talks': v['talks'],
                     'used': srt.units(v['talks']) * S.UNIT_MIN, 'coherence': coherence(space, v['talks'])[0], 'weakest': []})
    for r in rows:
        for k, i in enumerate(r['talks'], 1):
            assign[i] = {'talk_id': i, 'session_id': r['session_id'], 'order': k, 'locked': 'false', 'note': ''}
    for p in srt.state['pool']:
        assign[p['id']] = {'talk_id': p['id'], 'session_id': '', 'order': '', 'locked': 'false', 'note': 'held for the lead (views/flags.md)'}
    for i in srt.talks:
        assign.setdefault(i, {'talk_id': i, 'session_id': '', 'order': '', 'locked': 'false', 'note': 'in no session'})
    est = S.estimates(data_dir, [r for r in rows if r['area'] != 'VIRTUAL'], srt.cfg) if attendance else {}
    S.write_csv(os.path.join(sort_dir, 'sessions.csv'),
                ['session_id', 'title', 'kind', 'minutes', 'size', 'area', 'locked', 'scope', 'notes'], rows)
    S.write_csv(os.path.join(sort_dir, 'assignments.csv'), ['talk_id', 'session_id', 'order', 'locked', 'note'],
                sorted(assign.values(), key=lambda r: S.id_key(r['talk_id'])))
    with open(os.path.join(wdir(data_dir), 'log.jsonl'), encoding='utf-8') as f:
        log = [json.loads(l) for l in f if l.strip()]
    today = datetime.date.today().isoformat()
    first = collections.OrderedDict()
    for p in sorted(glob.glob(os.path.join(data_dir, 'work', 'sessions', '*', 'proposal.json'))):
        prop, data = S.load_area(p)
        for r in prop.get('released') or []:
            first[r['id']] = (data['limits']['area'], r['reason'])
    moves = [{'when': today, 'commit': '', 'talk_id': i, 'from': a, 'to': 'lonely', 'by': 'claude', 'reason': 'draft: ' + why}
             for i, (a, why) in first.items()]
    moves += [{'when': today, 'commit': '', 'talk_id': e['talk'], 'from': e['from'], 'to': e['to'] if e['to'] != 'pool' else 'lonely',
               'by': 'claude', 'reason': e['reason']} for e in log if e['op'] == 'move']
    S.write_csv(os.path.join(sort_dir, 'moves.csv'), ['when', 'commit', 'talk_id', 'from', 'to', 'by', 'reason'], moves)
    write_views(srt, rows, est, c, log, first)
    held = A.read_held(data_dir)
    keep = [r for r in held if r['stage'] != '6']
    listed = {r['talk_id'] for r in keep}
    keep += [{'talk_id': p['id'], 'stage': '6', 'action': p.get('action') or 'decide', 'unit': p.get('unit', ''), 'reason': p['reason']}
             for p in srt.state['pool'] if p['id'] not in listed]
    A.write_held(data_dir, keep)
    A.flags(data_dir)
    print(f"{len(rows)} sessions written; {len(srt.state['pool'])} talks held for the lead; views/packing_report.md")


def write_views(srt, rows, est, c, log, released):
    data_dir = srt.data_dir
    vdir = os.path.join(data_dir, 'views', 'sessions')
    os.makedirs(vdir, exist_ok=True)
    for f in glob.glob(os.path.join(vdir, '*.md')):
        os.remove(f)
    names = {a: v.get('name', '') for a, v in (srt.cfg.get('areas') or {}).items()}

    def block(r):
        e = est.get(r['session_id'])
        att = (f" · estimated peak {e['interest']} ({e['low']}–{e['high']}), suggested room {e['size']}"
               + (f" ({e['size_note']})" if e.get('size_note') else '')) if e else ''
        out = [f"### {r['session_id']}: {r['title']}", '',
               f"{r['minutes']} min, {r['used']} min filled · {r['kind']} · coherence {r['coherence']:.3f}{att}", '',
               f"_{r['scope']}_", '', '| ID | Title | Institution | Key claim |', '| --- | --- | --- | --- |']
        for i in r['talks']:
            t, cd = srt.talks[i], srt.cards.get(i) or {}
            b = '**' if t['type'] == 'invited' else ''
            weak = ' (weakest fit)' if i in r['weakest'] else ''
            out.append(f"| {i} | {b}{t['title']}{b}{weak} | {t['institution'] or t['affiliation']} | {cd.get('key_claim', '')} |")
        return out + ['']
    for area in sorted({r['area'] for r in rows}):
        mine = [r for r in rows if r['area'] == area]
        lines = [f"# {area}: {names.get(area, '')}", '', 'Generated by `dqi_sort.pack finish`; do not edit.', '']
        for r in mine:
            lines += block(r)
        with open(os.path.join(vdir, f'{area}.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines).rstrip() + '\n')
    inp = [r for r in rows if r['area'] != 'VIRTUAL']
    L = collections.Counter(r['minutes'] for r in inp)
    summ = ['# The sort', '', 'Generated by `dqi_sort.pack finish`; do not edit. Per-area detail in `views/sessions/`.', '',
            '| Review area | Sessions | 144 / 108 | Filled min / capacity | Mean coherence |', '| --- | --- | --- | --- | --- |']
    for area in sorted({r['area'] for r in rows}):
        mine = [r for r in rows if r['area'] == area]
        m = collections.Counter(r['minutes'] for r in mine)
        summ.append(f"| {area} | {len(mine)} | {m[144]} / {m[108]}{' / ' + str(m[120]) + ' virtual' if m[120] else ''} | "
                    f"{sum(r['used'] for r in mine)} / {sum(r['minutes'] for r in mine)} | {np.mean([r['coherence'] for r in mine]):.3f} |")
    summ += ['', f"In person: {L[144]} x 144 and {L[108]} x 108 against {srt.n144} x 144 and {srt.n108} x 108 slots; "
             f"{len(srt.state['pool'])} talks held for the lead."]
    if est:
        budget = S.room_budget(data_dir)
        want = collections.Counter(est[r['session_id']]['size'] for r in inp if r['session_id'] in est)
        summ += ['', '| Suggested room size | Sessions | Slots |', '| --- | --- | --- |']
        for k in sorted(srt.cfg.get('room_sizes') or {}, key=lambda k: srt.cfg['room_sizes'][k]):
            summ.append(f'| {k} | {want[k]} | {budget[k]} |')
    with open(os.path.join(data_dir, 'views', 'sessions.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(summ) + '\n')
    # packing report
    moves = [e for e in log if e['op'] == 'move']
    final = {}
    for e in moves:
        final[e['talk']] = e
    first_from = {}
    for e in moves:
        first_from.setdefault(e['talk'], e['from'])
    net = [(i, first_from[i], e['to'], e['reason']) for i, e in final.items() if first_from[i] != e['to']]
    title = {r['session_id']: r['title'] for r in rows}
    new = [e for e in log if e['op'] == 'new']
    rep = ['# Packing report (global pass)', '',
           f"{len(inp)} in-person sessions ({L[144]} x 144, {L[108]} x 108) against {srt.n144} x 144 and {srt.n108} x 108 slots. "
           f"{len(released)} talks released by the drafts; {len(net)} talks moved by the global pass (net); "
           f"{len(new)} sessions built in the global pass; {len(srt.state['pool'])} talks held for the lead.", '']
    if new:
        rep += ['## Sessions built in the global pass', '', '| Session | Title | Talks from | Why |', '| --- | --- | --- | --- |']
        for e in new:
            r = next((x for x in rows if x['session_id'] == e['session']), None)
            if r:
                src = collections.Counter(srt.talks[i]['area'] for i in r['talks'])
                rep.append(f"| {e['session']} | {r['title']} | {', '.join(f'{a} {n}' for a, n in src.most_common())} | {e['reason']} |")
        rep.append('')
    rep += ['## Every talk moved (draft session or pool → final session)', '', '| Talk | Title | From | To | Why |', '| --- | --- | --- | --- | --- |']
    for i, a, b, why in sorted(net, key=lambda x: (str(x[2]), S.id_key(x[0]))):
        rep.append(f"| {i} | {srt.talks[i]['title'][:70]} | {a} | {b}{(': ' + title[b][:40]) if b in title else ''} | {why} |")
    cross = [r for r in inp if len({srt.talks[i]['area'] for i in r['talks']}) > 1]
    rep += ['', f'## Sessions drawing talks from more than one draft area ({len(cross)})', '']
    rep += [f"- {r['session_id']} {r['title']}: " + ', '.join(f'{a} {n}' for a, n in collections.Counter(srt.talks[i]['area'] for i in r['talks']).most_common())
            for r in cross]
    rep += ['', '## Fill', '', '| Session | Title | Length | Filled |', '| --- | --- | --- | --- |']
    rep += [f"| {r['session_id']} | {r['title']} | {r['minutes']} | {r['used']} |" for r in inp if r['used'] < r['minutes']]
    rep += ['', '(Sessions not listed are full.)', '']
    if c['warnings']:
        rep += ['## Soft-rule exceptions', ''] + [f'- {w}' for w in c['warnings']] + ['']
    low = sorted(inp, key=lambda r: r['coherence'])[:10]
    rep += ['## Least coherent sessions (embedding check; worth a look)', ''] + [f"- {r['session_id']} {r['coherence']:.3f} {r['title']}" for r in low]
    if srt.state['pool']:
        rep += ['', '## Held for the lead', '', f"{len(srt.state['pool'])} talks are in no session. Each is listed with its card and the "
                'proposal (poster, another unit, or the lead decides) in views/flags.md, the one list of talks the lead must decide.']
    with open(os.path.join(data_dir, 'views', 'packing_report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(rep) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['start', 'ops', 'status', 'critique', 'finish'])
    ap.add_argument('data_dir')
    ap.add_argument('ops_file', nargs='?')
    ap.add_argument('--restart', action='store_true')
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--no-attendance', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'start':
        start(a.data_dir, a.restart)
    elif a.cmd == 'ops':
        if not a.ops_file:
            sys.exit('ops needs the OPS.json file')
        ops(a.data_dir, a.ops_file)
    elif a.cmd == 'status':
        print(status_text(Sort(a.data_dir).load()))
    elif a.cmd == 'critique':
        critique(a.data_dir)
    else:
        finish(a.data_dir, a.replace, not a.no_attendance)


if __name__ == '__main__':
    main()
