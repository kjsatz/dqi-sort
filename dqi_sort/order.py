"""Stage 9: talk order. Invited-talk positions per room, then each session re-ordered around its invited talk.

    python -m dqi_sort.order positions DATA_DIR [--seed 1]
    python -m dqi_sort.order prepare   DATA_DIR
    python -m dqi_sort.order apply     DATA_DIR
    python -m dqi_sort.order check     DATA_DIR

Sessions are built from 36-minute blocks (one invited talk, or three contributed talks). An invited talk starts a
block: talk number 1, 4, 7 or 10 in a 144-minute session, 1, 4 or 7 in a 108-minute one.

positions  gives each room a block for the invited talks of its 144- and 108-minute sessions (venue/rooms.csv
           invited_block_144, invited_block_108), chosen so that invited talks running at the same time stagger:
           a random search that minimises pairs of invited talks in the same time block and the same position,
           counted double for rooms in the same zone or of the same topic family. Writes views/invited_positions.md.
prepare    writes work/order/AREA/ for each area with sessions holding an invited talk: sessions.md (each such
           session with its room's block, a feasible block if that one cannot be reached, and every talk's card,
           series and requests) and prompt.md (prompts/order_spec.md). One Claude agent per area writes order.json.
apply      reads every order.json, checks each session (same talks; invited talks at block starts, the first at its
           room's block; series consecutive and in order) and writes the orders into sorting/assignments.csv.
check      the validator for every scheduled session: invited talks on 36-minute boundaries (at the room's block,
           unless that block cannot be reached), series consecutive and in order, and the session fits its slot.
"""
import argparse, collections, glob, json, os, random, sys
from dqi_sort import sessions as S

BLOCKS = {144: 4, 108: 3}


def load(data_dir):
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    assign = S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))
    members = collections.defaultdict(list)
    for a in sorted(assign, key=lambda a: float(a['order'] or 0)):
        if a['session_id'] and talks[a['talk_id']]['status'] == 'active':
            members[a['session_id']].append(a['talk_id'])
    slots = {s['slot_id']: s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
    sched = {r['session_id']: slots[r['slot_id']] for r in S.read_csv(os.path.join(data_dir, 'schedule', 'schedule.csv'))}
    rooms = {r['room_id']: r for r in S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    return talks, sess, assign, members, sched, rooms


def units(t):
    return int(t['minutes']) // S.UNIT_MIN


def feasible_blocks(talk_ids, talks, minutes):
    """Blocks (1-based) where an invited talk can start: the talks before it must fill exactly 3(k-1) units."""
    inv = [i for i in talk_ids if talks[i]['type'] == 'invited']
    n_oral = sum(units(talks[i]) for i in talk_ids if talks[i]['type'] != 'invited')
    out = []
    for k in range(1, BLOCKS[minutes] + 1):
        need = 3 * (k - 1)
        if any(need - 3 * b >= 0 and need - 3 * b <= n_oral for b in range(len(inv))):
            out.append(k)
    return out


def target_block(sid, members, talks, sched, rooms):
    s = sched[sid]
    room = rooms.get(s['room_id']) or {}
    want = room.get(f"invited_block_{s['minutes']}")
    ok = feasible_blocks(members[sid], talks, int(s['minutes']))
    want = int(want) if want else 1
    return want, (want if want in ok else min(ok, key=lambda k: (abs(k - want), k)))


def blocks_of(order, talks):
    """{talk_id: block number} for invited talks that start on a block boundary, and the list that do not."""
    pos, at, off = 0, {}, []
    for i in order:
        if talks[i]['type'] == 'invited':
            if pos % 3:
                off.append(i)
            else:
                at[i] = pos // 3 + 1
        pos += units(talks[i])
    return at, off


def session_problems(sid, order, talks, sched, rooms, members):
    errs = []
    if sorted(order) != sorted(members[sid]):
        return [f'{sid}: the order must list exactly the session\'s talks']
    at, off = blocks_of(order, talks)
    errs += [f'{sid}: invited talk {i} does not start a 36-minute block' for i in off]
    if at and sid in sched and sched[sid]['room_id']:
        want, reach = target_block(sid, members, talks, sched, rooms)
        first = min(at.values())
        if reach not in at.values():
            errs.append(f"{sid}: no invited talk at block {reach} (the room's block{'' if reach == want else f' {want} cannot be reached'})")
    series = collections.defaultdict(list)
    for n, i in enumerate(order):
        if talks[i]['series']:
            series[talks[i]['series']].append((n, int(talks[i]['series_part'] or 0)))
    for sname, v in series.items():
        idx = [n for n, _ in v]
        if idx != list(range(idx[0], idx[0] + len(idx))) or [p for _, p in v] != sorted(p for _, p in v):
            errs.append(f'{sid}: series {sname} is not consecutive and in part order')
    used = sum(int(talks[i]['minutes']) for i in order)
    if sid in sched and used > int(sched[sid]['minutes']):
        errs.append(f'{sid}: {used} minutes in a {sched[sid]["minutes"]}-minute slot')
    return errs


# ---------- positions ----------
def positions(data_dir, seed=1, iters=20000):
    talks, sess, assign, members, sched, rooms = load(data_dir)
    cfg = S.load_config(data_dir)
    fam_of = lambda sid: ((cfg.get('areas') or {}).get(sess[sid]['area'], {}) or {}).get('modality') or sess[sid]['area']
    fams = collections.defaultdict(collections.Counter)
    for sid, s in sched.items():
        if s['room_id']:
            fams[s['room_id']][fam_of(sid)] += 1
    family = {r: c.most_common(1)[0][0] for r, c in fams.items()}
    inv_sessions = [sid for sid in sched if sched[sid]['room_id'] and any(talks[i]['type'] == 'invited' for i in members[sid])]
    by_block = collections.defaultdict(list)
    for sid in inv_sessions:
        by_block[(sched[sid]['day'], sched[sid]['start'])].append(sid)
    room_ids = sorted(fams)
    rnd = random.Random(seed)
    pos = {(r, m): rnd.randint(1, BLOCKS[m]) for r in room_ids for m in BLOCKS}

    def block_of(sid):
        s = sched[sid]
        want = pos[(s['room_id'], int(s['minutes']))]
        ok = feasible_blocks(members[sid], talks, int(s['minutes']))
        return want if want in ok else min(ok, key=lambda k: (abs(k - want), k))

    def cost():
        c = 0
        for v in by_block.values():
            for a in range(len(v)):
                for b in range(a + 1, len(v)):
                    if block_of(v[a]) == block_of(v[b]):
                        ra, rb = sched[v[a]]['room_id'], sched[v[b]]['room_id']
                        c += 1 + (rooms[ra]['zone'] == rooms[rb]['zone']) + (family[ra] == family[rb])
        return c
    cur = cost()
    for _ in range(iters):
        key = rnd.choice(list(pos))
        old = pos[key]
        pos[key] = rnd.randint(1, BLOCKS[key[1]])
        new = cost()
        if new <= cur:
            cur = new
        else:
            pos[key] = old
    rows = S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))
    for r in rows:
        r['invited_block_144'] = pos.get((r['room_id'], 144), '')
        r['invited_block_108'] = pos.get((r['room_id'], 108), '')
    S.write_csv(os.path.join(data_dir, 'venue', 'rooms.csv'), list(rows[0].keys()), rows)
    talk_no = lambda k: 3 * (k - 1) + 1
    lines = ['# Invited-talk positions', '', 'Generated by `python -m dqi_sort.order positions`; do not edit. An invited talk starts block k, which is '
             'talk number 1, 4, 7 or 10 (block 1 to 4) when the talks before it are contributed.', '',
             '| Room | Zone | Topic family | 144-min sessions: block (talk no.) | 108-min sessions: block (talk no.) |', '| --- | --- | --- | --- | --- |']
    lines += [f"| {r} | {rooms[r]['zone']} | {family[r]} | {pos[(r, 144)]} ({talk_no(pos[(r, 144)])}) | {pos[(r, 108)]} ({talk_no(pos[(r, 108)])}) |"
              for r in room_ids]
    same = sum(1 for v in by_block.values() for a in range(len(v)) for b in range(a + 1, len(v)) if block_of(v[a]) == block_of(v[b]))
    total = sum(len(v) * (len(v) - 1) // 2 for v in by_block.values())
    lines += ['', f'{len(inv_sessions)} sessions hold an invited talk. Pairs of invited talks in the same time block: {total}; '
              f'at the same position: {same}.', '', '## By time block', '']
    for b in sorted(by_block, key=lambda b: (['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].index(b[0]), b[1])):
        lines.append(f"- {b[0]} {b[1]}: " + ', '.join(f"{sid} ({sched[sid]['room_id']}) talk {talk_no(block_of(sid))}"
                                                      for sid in sorted(by_block[b], key=block_of)))
    with open(os.path.join(data_dir, 'views', 'invited_positions.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[4:4 + len(room_ids) + 4]))


# ---------- prepare / apply ----------
def prepare(data_dir):
    talks, sess, assign, members, sched, rooms = load(data_dir)
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    series_parts = collections.Counter(t['series'] for t in talks.values() if t['series'] and t['status'] == 'active')
    with open(os.path.join(S.HERE, 'prompts', 'order_spec.md'), encoding='utf-8') as f:
        spec = f.read()
    by_area = collections.defaultdict(list)
    for sid in sorted(sched):
        if any(talks[i]['type'] == 'invited' for i in members[sid]):
            by_area[sess[sid]['area']].append(sid)
    root = os.path.join(data_dir, 'work', 'order')
    for area, sids in sorted(by_area.items()):
        d = os.path.join(root, area)
        os.makedirs(d, exist_ok=True)
        lines = [f'# {area}: sessions with an invited talk ({len(sids)})', '']
        for sid in sids:
            s = sched[sid]
            want, reach = target_block(sid, members, talks, sched, rooms)
            n_inv = sum(talks[i]['type'] == 'invited' for i in members[sid])
            lines += [f"## {sid}: {sess[sid]['title']} ({s['minutes']} min, {s['day']} {s['start']}, room {s['room_id']})", '',
                      f"Invited talk at block {reach} (talk number {3 * (reach - 1) + 1})" + ('' if reach == want else f" (the room's block {want} cannot be reached)")
                      + ('; this session has two invited talks: the other goes at another block start.' if n_inv > 1 else '.'), '',
                      'Current order:', '']
            lines += [S.card_text(talks[i], cards.get(i), series_parts) for i in members[sid]] + ['']
        with open(os.path.join(d, 'sessions.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        check_cmd = f"cd {S.HERE} && .venv/bin/python -m dqi_sort.order apply {os.path.abspath(data_dir)} --only {area} --dry-run"
        with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
            f.write(spec.replace('{DIR}', os.path.abspath(d)).replace('{AREA}', area).replace('{CHECK}', check_cmd))
        print(f'{area}: {len(sids)} sessions -> {d}')


def apply(data_dir, only=None, dry_run=False):
    talks, sess, assign, members, sched, rooms = load(data_dir)
    errs, orders = [], {}
    for path in sorted(glob.glob(os.path.join(data_dir, 'work', 'order', '*', 'order.json'))):
        area = os.path.basename(os.path.dirname(path))
        if only and area != only:
            continue
        with open(path, encoding='utf-8') as f:
            got = json.load(f)
        for sid, order in got.items():
            order = [str(x) for x in order]
            e = session_problems(sid, order, talks, sched, rooms, members)
            errs += e
            if not e:
                orders[sid] = order
    for e in errs:
        print('ERROR', e)
    if dry_run or errs:
        print(f"{len(orders)} sessions OK{'' if not errs else f', {len(errs)} errors'}")
        return errs
    for a in assign:
        if a['session_id'] in orders:
            a['order'] = orders[a['session_id']].index(a['talk_id']) + 1
    S.write_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'), ['talk_id', 'session_id', 'order', 'locked', 'note'], assign)
    print(f'{len(orders)} sessions re-ordered in sorting/assignments.csv')
    return errs


def check(data_dir):
    talks, sess, assign, members, sched, rooms = load(data_dir)
    errs = [e for sid in sorted(sched) for e in session_problems(sid, members[sid], talks, sched, rooms, members)]
    for e in errs:
        print('ERROR', e)
    print(f'{len(sched)} sessions checked: {len(errs)} problems')
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['positions', 'prepare', 'apply', 'check'])
    ap.add_argument('data_dir')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--only')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'positions':
        positions(a.data_dir, a.seed)
    elif a.cmd == 'prepare':
        prepare(a.data_dir)
    elif a.cmd == 'apply':
        sys.exit(1 if apply(a.data_dir, a.only, a.dry_run) else 0)
    else:
        sys.exit(1 if check(a.data_dir) else 0)


if __name__ == '__main__':
    main()
