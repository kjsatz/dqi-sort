"""The validator: the checks in PROCESS.md (Data, rule 5) as one command, plus the reconciliation with APS's list.

    python -m dqi_sort.validate DATA_DIR [--delivery]

Checks whatever exists so far (the sort, the schedule, the talk order, the chairs) and prints ERROR and WARN lines;
exits 1 on any ERROR.
- Talks: every active talk is in exactly one session or in the lonely pool; no other talk is in a session; every
  assignment names a known talk and session.
- Sessions: talks of one track only (the hard partition); within length, and not more than one 12-minute slot short;
  speaking orders set and distinct; invited talks start a 36-minute block (at the room's block once scheduled);
  series consecutive and in part order (and in one session); at most max_same_institution talks from one institution;
  the in-person session count within session_budget.
- Schedule (once schedule/schedule.csv exists): every session in exactly one slot of its track and length, no slot
  used twice, room size as decided; no speaker in two sessions at overlapping times.
- Chairs (once chairs/chairs.csv has confirmed chairs): one per session, two per virtual session; no chair speaks in
  the session they chair, presents at the same time, or chairs two sessions at once.
- Reconciliation: the APS input list against the delivered list (talks in a session). Every omission (a talk in
  APS's list that is in no session) and every addition (a talk in a session that is not in APS's list) must be a
  logged decision in sorting/status_log.csv: exchanged to another unit, poster, duplicate or withdrawn; received from
  another unit or a late addition.

--delivery makes the checks that must hold before the APS sheet is written errors rather than warnings: the lonely
pool is empty, no talk is still offered to another unit, every session is scheduled and has its chairs, nothing in
the reconciliation is unexplained.
"""
import argparse, collections, os, re, sys
from dqi_sort import intake, sessions as S
from dqi_sort.order import blocks_of, session_problems

GONE = {'other_unit': 'exchanged to another unit', 'poster': 'poster', 'duplicate': 'duplicate', 'withdrawn': 'withdrawn'}


def norm(name):
    return ''.join(ch for ch in (name or '').casefold() if ch.isalnum())


def read(data_dir, *parts):
    p = os.path.join(data_dir, *parts)
    return S.read_csv(p) if os.path.exists(p) else []


def load(data_dir):
    """Everything the checks need, as one dict. Missing later-stage files are empty."""
    cfg = S.load_config(data_dir)
    talks = {t['talk_id']: t for t in read(data_dir, 'talks.csv')}
    sess = {s['session_id']: s for s in read(data_dir, 'sorting', 'sessions.csv')}
    assign = read(data_dir, 'sorting', 'assignments.csv')
    members = collections.defaultdict(list)
    for a in sorted(assign, key=lambda a: float(a['order'] or 0)):
        if a['session_id'] and a['talk_id'] in talks and talks[a['talk_id']]['status'] == 'active':
            members[a['session_id']].append(a['talk_id'])
    slots = {s['slot_id']: s for s in read(data_dir, 'schedule', 'slots.csv')}
    schedule = read(data_dir, 'schedule', 'schedule.csv')
    sched = {r['session_id']: slots[r['slot_id']] for r in schedule if r['slot_id'] in slots}
    rooms = {r['room_id']: r for r in read(data_dir, 'venue', 'rooms.csv')}
    chairs = [c for c in read(data_dir, 'chairs', 'chairs.csv') if str(c.get('confirmed', '')).strip().upper() == 'TRUE']
    log = read(data_dir, 'sorting', 'status_log.csv')
    return dict(cfg=cfg, talks=talks, sess=sess, assign=assign, members=members, slots=slots, schedule=schedule,
                sched=sched, rooms=rooms, chairs=chairs, log=log, aps=aps_lists(data_dir, cfg))


def aps_lists(data_dir, cfg):
    """{track: (header, rows, id column)} for each APS input table that exists."""
    colmap = {k.strip(): v for k, v in (cfg.get('aps_columns') or {}).items()}
    out = {}
    for track, spec in (cfg.get('aps_input') or {}).items():
        if os.path.exists(os.path.join(data_dir, spec['file'])):
            out[track] = intake.raw_rows(data_dir, spec, colmap)
    return out


def is_virtual(s):
    return s.get('area') == 'VIRTUAL'


def overlap(a, b):
    return a['day'] == b['day'] and a['start'] < b['end'] and b['start'] < a['end']


def chair_codes(c):
    return [x for x in re.split(r'[;,\s]+', (c.get('session') or '').upper()) if x]


# ---------- the checks ----------
def check_talks(d, delivery):
    talks, sess = d['talks'], d['sess']
    out, seen = [], collections.Counter(a['talk_id'] for a in d['assign'])
    out += [('ERROR', f'{i}: in sorting/assignments.csv {n} times') for i, n in seen.items() if n > 1]
    out += [('ERROR', f"{a['talk_id']}: in sorting/assignments.csv but not in talks.csv") for a in d['assign'] if a['talk_id'] not in talks]
    out += [('ERROR', f"{a['talk_id']}: in session {a['session_id']}, which does not exist") for a in d['assign']
            if a['session_id'] and a['session_id'] not in sess]
    where = {a['talk_id']: a['session_id'] for a in d['assign']}
    for i, t in talks.items():
        if t['status'] == 'active' and i not in where:
            out.append(('ERROR', f'{i}: active but neither in a session nor in the lonely pool (no row in assignments.csv)'))
        elif t['status'] != 'active' and where.get(i):
            out.append(('ERROR', f"{i}: status {t['status']} but still in session {where[i]}"))
    lonely = sorted((i for i, s in where.items() if not s and talks.get(i, {}).get('status') == 'active'), key=S.id_key)
    if lonely:
        out.append(('ERROR' if delivery else 'WARN', f"{len(lonely)} lonely abstracts (the pool must be empty at delivery): {', '.join(lonely[:12])}"
                    + (' ...' if len(lonely) > 12 else '')))
    pending = sorted((i for i, t in talks.items() if t['status'] == 'exchange_pending'), key=S.id_key)
    if pending:
        out.append(('ERROR' if delivery else 'WARN', f"{len(pending)} talks still offered to another unit: {', '.join(pending)}"))
    return out


def check_sessions(d, delivery):
    talks, sess, members, cfg = d['talks'], d['sess'], d['members'], d['cfg']
    out, cap_inst = [], int(cfg.get('max_same_institution') or 4)
    orders = collections.defaultdict(list)
    for a in d['assign']:
        if a['session_id'] in members and a['talk_id'] in members[a['session_id']]:
            orders[a['session_id']].append(a['order'])
    series_at = collections.defaultdict(set)
    for sid, s in sorted(sess.items()):
        m = members[sid]
        if not m:
            out.append(('WARN', f'{sid}: no talks'))
            continue
        wrong = [i for i in m if (talks[i]['track'] == 'virtual') != is_virtual(s)]
        out += [('ERROR', f"{sid}: {i} is a {talks[i]['track']} talk in a session of the other track") for i in wrong]
        if any(not o for o in orders[sid]) or len(set(orders[sid])) < len(orders[sid]):
            out.append(('ERROR', f'{sid}: speaking orders missing or repeated'))
        used, cap = sum(int(talks[i]['minutes']) for i in m), int(s['minutes'])
        if used > cap:
            out.append(('ERROR', f'{sid}: {used} minutes of talks in a {cap}-minute session'))
        elif used < cap - S.UNIT_MIN:
            out.append(('WARN', f'{sid}: {cap - used} minutes empty'))
        sched = d['sched'] if sid in d['sched'] else {}
        for e in session_problems(sid, m, talks, sched, d['rooms'], members):
            if 'minutes in a' not in e or used <= cap:            # length is reported above
                out.append(('ERROR', e))
        for i in m:
            if talks[i]['series']:
                series_at[talks[i]['series']].add(sid)
        inst = collections.Counter(talks[i]['institution'] or talks[i]['affiliation'] for i in m)
        out += [('WARN', f'{sid}: {n} talks from {k} (more than {cap_inst})') for k, n in inst.items() if k and n > cap_inst]
    out += [('WARN', f"series {k} is split over sessions {', '.join(sorted(v))}") for k, v in sorted(series_at.items()) if len(v) > 1]
    budget = cfg.get('session_budget')
    n_ip = sum(1 for s in sess.values() if not is_virtual(s))
    if budget and n_ip > int(budget):
        out.append(('ERROR', f'{n_ip} in-person sessions, over the budget of {budget}'))
    return out


def check_schedule(d, delivery):
    if not d['schedule']:
        return [('ERROR', 'no schedule (schedule/schedule.csv)')] if delivery else []
    talks, sess, sched, rooms, members = d['talks'], d['sess'], d['sched'], d['rooms'], d['members']
    out = []
    count = collections.Counter(r['session_id'] for r in d['schedule'])
    out += [('ERROR', f'{sid}: scheduled {n} times') for sid, n in count.items() if n > 1]
    out += [('ERROR', f"{r['session_id']}: scheduled but not in sessions.csv") for r in d['schedule'] if r['session_id'] not in sess]
    out += [('ERROR', f"{r['session_id']}: slot {r['slot_id']} is not in schedule/slots.csv") for r in d['schedule'] if r['slot_id'] not in d['slots']]
    used = collections.Counter(r['slot_id'] for r in d['schedule'])
    out += [('ERROR', f'slot {k} holds {n} sessions') for k, n in used.items() if n > 1]
    for sid, s in sorted(sess.items()):
        if sid not in sched:
            out.append(('ERROR' if delivery else 'WARN', f'{sid}: not scheduled'))
            continue
        slot = sched[sid]
        if (slot['track'] == 'virtual') != is_virtual(s):
            out.append(('ERROR', f"{sid}: in a {slot['track']} slot ({slot['slot_id']})"))
        if int(slot['minutes']) != int(s['minutes']):
            out.append(('ERROR', f"{sid}: a {s['minutes']}-minute session in a {slot['minutes']}-minute slot ({slot['slot_id']})"))
        room = rooms.get(slot.get('room_id') or '')
        if room and s.get('size') and room.get('size') and room['size'] != s['size']:
            out.append(('WARN', f"{sid}: size {s['size']}, in room {room['room_id']} ({room['size']})"))
    when = collections.defaultdict(set)          # speaker -> sessions
    for sid, m in members.items():
        if sid in sched:
            for i in m:
                when[norm(talks[i]['speaker'])].add(sid)
    for who, sids in sorted(when.items()):
        sids = sorted(sids)
        for a in range(len(sids)):
            for b in range(a + 1, len(sids)):
                if who and overlap(sched[sids[a]], sched[sids[b]]):
                    names = {talks[i]['speaker'] for i in members[sids[a]] if norm(talks[i]['speaker']) == who}
                    out.append(('ERROR', f"{', '.join(sorted(names))} speaks in {sids[a]} and {sids[b]} at overlapping times"))
    return out


def check_chairs(d, delivery):
    talks, sess, sched, members = d['talks'], d['sess'], d['sched'], d['members']
    if not d['chairs'] and not delivery:
        return []
    out, have = [], collections.defaultdict(list)
    for c in d['chairs']:
        for x in chair_codes(c):
            if x not in sess:
                out.append(('ERROR', f"chair {c['name']}: no session {x}"))
            else:
                have[x].append(c)
    for sid, s in sorted(sess.items()):
        need = 2 if is_virtual(s) else 1
        n = len(have[sid])
        if n < need:
            out.append(('ERROR' if delivery else 'WARN', f'{sid}: {n} of {need} chairs'))
        elif n > need:
            out.append(('WARN', f"{sid}: {n} chairs, {need} needed ({', '.join(c['name'] for c in have[sid])})"))
    speaks = collections.defaultdict(set)
    for sid, m in members.items():
        for i in m:
            speaks[norm(talks[i]['speaker'])].add(sid)
    for c in d['chairs']:
        mine = [x for x in chair_codes(c) if x in sess]
        own = speaks.get(norm(c['name']), set())
        for x in mine:
            if x in own:
                out.append(('ERROR', f"chair {c['name']} speaks in {x}, the session they chair"))
            elif x in sched:
                clash = sorted(y for y in own if y in sched and overlap(sched[x], sched[y]))
                if clash:
                    out.append(('ERROR', f"chair {c['name']} chairs {x} while speaking in {', '.join(clash)}"))
        timed = [x for x in mine if x in sched]
        for a in range(len(timed)):
            for b in range(a + 1, len(timed)):
                if overlap(sched[timed[a]], sched[timed[b]]):
                    out.append(('ERROR', f"chair {c['name']} chairs {timed[a]} and {timed[b]} at overlapping times"))
    return out


def reconcile(d):
    """The APS input list against the delivered list. Returns (summary dict, problems).

    Omitted: in APS's list, in no session. Added: in a session, not in APS's list. Each must be a logged decision."""
    talks, log = d['talks'], d['log']
    placed = {i for m in d['members'].values() for i in m}
    given = {}
    for track, (header, rows, k) in d['aps'].items():
        for r in rows:
            given[r[k].strip()] = track
    last = {}
    for r in log:
        last.setdefault(r['talk_id'], []).append(r)
    out, omitted, added = [], [], []
    for i in sorted(given, key=S.id_key):
        t = talks.get(i)
        if t is None:
            out.append(('ERROR', f'{i}: in the APS input but not in talks.csv (run intake)'))
            continue
        if t['track'] != given[i]:
            out.append(('ERROR', f"{i}: {given[i]} in the APS input but {t['track']} in talks.csv"))
        if i in placed:
            continue
        entry = next((r for r in reversed(last.get(i, [])) if r['to_status'] == t['status']), None)
        if t['status'] in GONE and entry:
            omitted.append((i, t['status'], entry))
        elif t['status'] in GONE:
            out.append(('ERROR', f"{i}: status {t['status']}, but no decision for it in sorting/status_log.csv"))
        # active (lonely) and exchange_pending talks are reported by check_talks
    for i in sorted(placed - set(given), key=S.id_key):
        entry = next((r for r in reversed(last.get(i, [])) if r['from_status'] == 'new' or r['from_status'].startswith('in ')), None)
        if entry:
            added.append((i, entry))
        else:
            out.append(('ERROR', f'{i}: in a session but not in the APS input, and not logged as received or as a late addition'))
    summary = {'input': len(given), 'placed': len(placed), 'omitted': omitted, 'added': added,
               'by_track': collections.Counter(given.values())}
    return summary, out


def why(status, entry):
    unit = entry.get('unit') or ''
    note = entry.get('note') or ''
    head = {'other_unit': f'exchanged to {unit}' if unit else 'exchanged to another unit', 'poster': 'poster',
            'duplicate': 'duplicate', 'withdrawn': 'withdrawn'}.get(status, status)
    return head + (f' ({entry["when"][:10]}): {note}' if note else f' ({entry["when"][:10]})')


def short(status, entry):
    """The sorter note on APS's sheet for a talk in no session: what happened, briefly."""
    if status == 'other_unit':
        return f"Exchanged to {entry.get('unit')}" if entry.get('unit') else 'Exchanged to another unit'
    if status == 'duplicate':
        m = re.search(r'duplicate of (\d+)', entry.get('note') or '')
        return f'Duplicate of {m.group(1)}' if m else 'Duplicate'
    return status.capitalize()


def why_added(entry):
    f = entry['from_status']
    head = f'received from {f[3:]}' if f.startswith('in ') else 'late addition'
    return head + f" ({entry['when'][:10]})" + (f": {entry['note']}" if entry.get('note') else '')


def reconciliation_text(summary):
    lines = [f"APS input: {summary['input']} talks ({', '.join(f'{k} {v}' for k, v in sorted(summary['by_track'].items()))}); "
             f"delivered in sessions: {summary['placed']}; omitted {len(summary['omitted'])}, added {len(summary['added'])} "
             f"({summary['input']} - {len(summary['omitted'])} + {len(summary['added'])} = {summary['input'] - len(summary['omitted']) + len(summary['added'])})."]
    if summary['omitted']:
        lines += ['', 'Omitted (in the APS input, in no session):'] + [f'- {i}: {why(s, e)}' for i, s, e in summary['omitted']]
    if summary['added']:
        lines += ['', 'Added (in a session, not in the APS input):'] + [f'- {i}: {why_added(e)}' for i, e in summary['added']]
    return '\n'.join(lines)


def validate(data_dir, delivery=False, quiet=False):
    """All problems as (level, text), and the reconciliation summary."""
    d = load(data_dir)
    probs = []
    for f in (check_talks, check_sessions, check_schedule, check_chairs):
        probs += f(d, delivery)
    summary, rp = reconcile(d)
    probs += rp
    if summary['input'] - len(summary['omitted']) + len(summary['added']) != summary['placed'] and not any(l == 'ERROR' for l, _ in probs):
        probs.append(('ERROR', 'the reconciliation does not add up'))
    if not quiet:
        for level, text in probs:
            print(level, text)
        print(reconciliation_text(summary))
        n = collections.Counter(l for l, _ in probs)
        print(f"{n['ERROR']} errors, {n['WARN']} warnings" + (' (delivery checks)' if delivery else ''))
    return probs, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--delivery', action='store_true', help='the stricter checks before the APS sheet is written')
    a = ap.parse_args()
    probs, _ = validate(a.data_dir, a.delivery)
    sys.exit(1 if any(l == 'ERROR' for l, _ in probs) else 0)


if __name__ == '__main__':
    main()
