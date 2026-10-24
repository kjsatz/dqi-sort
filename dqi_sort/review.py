"""Stage 7: read returned area sheets back into git.

    python -m dqi_sort.review read  DATA_DIR AREA
    python -m dqi_sort.review apply DATA_DIR AREA
    python -m dqi_sort.review move  DATA_DIR TALK TO [--position N] --reason TEXT [--by claude]
    python -m dqi_sort.review homes DATA_DIR [TALK ...]

read   fetches the area's current round (sorting/sheets.csv) and compares it with the version that was sent: the sort
       at the commit stamped on the sheet. It writes work/review/AREA-rN/changes.json and report.md: talks moved
       between sessions, reordered, ticked for the lonely pool, added (from the pool or another area) or missing;
       session titles, room size overrides, every note, and the sheet's freeform comments for Claude (the box at the
       top of the Session summary), which Claude reads and acts on first. Columns are found by their header names.
apply  applies those changes to the current sort (a three-way merge): a change is applied only if the talk is still
       where the sheet found it (otherwise it is a conflict, listed and skipped). It updates sorting/assignments.csv
       and sorting/sessions.csv, appends to sorting/moves.csv (by the reviewer) and sorting/notes.csv (every note and
       the freeform comments, resolution blank), records the round in sorting/reviews.csv, and reports sessions that no longer fit their
       length. Claude then acts on the notes with `move` and opens one pull request for the area.
move   moves one talk to a session (at a position, default the end) or to "lonely", with a reason, during review.
homes  for each talk named (default: every lonely abstract), the sessions closest to it by content (card embeddings),
       with their fill and whether their area's round is out. A reviewer who ticks a talk for the pool only means
       "not in this session": Claude looks here for a good home at once and moves it (or makes a small swap) when
       the fit is clearly good, and leaves it lonely for the end-of-review clean-up when it is not.

A round is applied once. sync-sheets makes no new round for an area whose current round is out (not applied yet)
and has a Status: the reviewer keeps the sheet they started, and changes from elsewhere wait for the next round.
"""
import argparse, collections, csv, datetime, io, json, os, subprocess, sys
from dqi_sort import sessions as S

MOVE_COLS = ['when', 'commit', 'talk_id', 'from', 'to', 'by', 'reason']
NOTE_COLS = ['round', 'area', 'reviewer', 'talk_id', 'session_id', 'note', 'resolution']
REVIEW_COLS = ['area', 'round', 'commit', 'sheet_id', 'applied', 'reviewer', 'changes', 'conflicts']


def git_csv(data_dir, commit, path):
    out = subprocess.run(['git', '-C', data_dir, 'show', f'{commit}:{path}'], capture_output=True, text=True, check=True).stdout
    return list(csv.DictReader(io.StringIO(out)))


def current_round(data_dir, area):
    rows = [r for r in S.read_csv(os.path.join(data_dir, 'sorting', 'sheets.csv')) if r['kind'] == 'area' and r['area'] == area]
    if not rows:
        sys.exit(f'no sheet was made for {area}')
    return rows[-1]


def reviewer(data_dir, area):
    path = os.path.join(data_dir, 'sorting', 'area_status.csv')
    rows = {r['area']: r for r in S.read_csv(path)} if os.path.exists(path) else {}
    return (rows.get(area) or {}).get('responsible') or 'reviewer'


def table(sheets, sid, tab):
    vals = sheets.spreadsheets().values().get(spreadsheetId=sid, range=f"'{tab}'!A2:Z2000").execute(num_retries=5).get('values', [])
    header = [h.strip() for h in vals[0]] if vals else []
    return [dict(zip(header, r + [''] * (len(header) - len(r)))) for r in vals[1:]]


def comments(row1):
    """The reviewer's freeform comments for Claude: the text after the label in row 1 of the Session summary."""
    from dqi_sort.sheets import COMMENTS_LABEL
    cells = [str(c).strip() for c in row1]
    if COMMENTS_LABEL not in cells:
        return ''
    return '\n'.join(c for c in cells[cells.index(COMMENTS_LABEL) + 1:] if c)


def wdir(data_dir, area, rnd):
    return os.path.join(data_dir, 'work', 'review', f'{area}-r{rnd}')


# ---------- read ----------
def diff(sent_assign, sent_sess, area, rows, summary):
    """What the reviewer changed, from the sheet's rows against the sort that was sent."""
    mine = {s['session_id'] for s in sent_sess if s['area'] == area}
    sent = {a['talk_id']: a for a in sent_assign if a['session_id'] in mine}
    ch = {'moves': [], 'kicked': [], 'added': [], 'missing': [], 'orders': {}, 'titles': [], 'sizes': [], 'notes': []}
    seen = set()
    by_session = collections.defaultdict(list)
    for k, r in enumerate(rows):
        i = str(r.get('Talk ID', '')).strip()
        if not i:
            continue
        seen.add(i)
        sess = str(r.get('Session', '')).strip()
        if str(r.get('Move to lonely abstracts', '')).strip().upper() == 'TRUE':
            ch['kicked'].append({'talk': i, 'from': sent[i]['session_id'] if i in sent else sess})
        elif i not in sent:
            ch['added'].append({'talk': i, 'to': sess})
            by_session[sess].append((k, r, i))
        else:
            if sess != sent[i]['session_id']:
                ch['moves'].append({'talk': i, 'from': sent[i]['session_id'], 'to': sess})
            by_session[sess].append((k, r, i))
        if str(r.get('Notes', '')).strip():
            ch['notes'].append({'talk': i, 'session': sess, 'note': str(r['Notes']).strip()})
    ch['missing'] = sorted((i for i in sent if i not in seen), key=S.id_key)
    for sess, items in by_session.items():
        def key(x):
            try:
                return (float(x[1].get('Order') or 1e9), x[0])
            except ValueError:
                return (1e9, x[0])
        new = [i for _, _, i in sorted(items, key=key)]
        old = [a['talk_id'] for a in sorted((a for a in sent_assign if a['session_id'] == sess), key=lambda a: float(a['order'] or 0))]
        if new != [i for i in old if i in new]:
            ch['orders'][sess] = new
    titles = {s['session_id']: s for s in sent_sess}
    for r in summary:
        sid = str(r.get('Session', '')).strip()
        if sid not in titles:
            continue
        if str(r.get('Title', '')).strip() and str(r['Title']).strip() != titles[sid]['title']:
            ch['titles'].append({'session': sid, 'from': titles[sid]['title'], 'to': str(r['Title']).strip()})
        if str(r.get('Room size override', '')).strip():
            ch['sizes'].append({'session': sid, 'size': str(r['Room size override']).strip()})
        if str(r.get('Notes', '')).strip() and str(r['Notes']).strip() != titles[sid].get('notes', ''):
            ch['notes'].append({'talk': '', 'session': sid, 'note': str(r['Notes']).strip()})
    return ch


def report_text(area, rnd, commit, ch, talks):
    t = lambda i: talks.get(i, {}).get('title', '')[:70]
    out = [f'# {area} round {rnd}: what the reviewer changed', '', f'Compared with the sort at {commit}, the version sent.', '']
    n = sum(len(ch[k]) for k in ('moves', 'kicked', 'added', 'titles', 'sizes', 'notes')) + len(ch['orders'])
    out.append(f'{n} changes: {len(ch["moves"])} moved, {len(ch["kicked"])} to the lonely pool, {len(ch["added"])} added, '
               f'{len(ch["orders"])} sessions reordered, {len(ch["titles"])} retitled, {len(ch["sizes"])} room sizes, {len(ch["notes"])} notes.')
    if ch['missing']:
        out += ['', f'**Missing from the sheet ({len(ch["missing"])}), neither in a session nor ticked for the pool:** '
                + ', '.join(f'{i} {t(i)}' for i in ch['missing'])]
    for title, key, fmt in (('Moved', 'moves', lambda c: f"{c['talk']} {t(c['talk'])}: {c['from']} → {c['to']}"),
                            ('To the lonely pool', 'kicked', lambda c: f"{c['talk']} {t(c['talk'])} (from {c['from']})"),
                            ('Added', 'added', lambda c: f"{c['talk']} {t(c['talk'])} → {c['to']}"),
                            ('Retitled', 'titles', lambda c: f"{c['session']}: {c['from']} → {c['to']}"),
                            ('Room size override', 'sizes', lambda c: f"{c['session']}: {c['size']}"),
                            ('Notes', 'notes', lambda c: f"{c['talk'] or c['session']}" + (f" ({t(c['talk'])})" if c['talk'] else '') + f": {c['note']}")):
        if ch[key]:
            out += ['', f'## {title}', ''] + [f'- {fmt(c)}' for c in ch[key]]
    if ch['orders']:
        out += ['', '## Reordered', ''] + [f'- {s}: ' + ', '.join(v) for s, v in ch['orders'].items()]
    if ch.get('comments'):
        out += ['', '## Freeform comments for Claude', '', 'Read and act on these before applying; say in the pull request what was done with each.',
                ''] + ['> ' + line for line in ch['comments'].split('\n')]
    return '\n'.join(out) + '\n'


def read(data_dir, area):
    from dqi_sort import gsheets
    r = current_round(data_dir, area)
    _, sheets = gsheets.services()
    rows, summary = table(sheets, r['sheet_id'], 'Sessions'), table(sheets, r['sheet_id'], 'Session summary')
    row1 = sheets.spreadsheets().values().get(spreadsheetId=r['sheet_id'], range="'Session summary'!A1:Z1").execute(num_retries=5).get('values', [[]])
    sent_assign = git_csv(data_dir, r['commit'], 'sorting/assignments.csv')
    sent_sess = git_csv(data_dir, r['commit'], 'sorting/sessions.csv')
    ch = diff(sent_assign, sent_sess, area, rows, summary)
    ch['comments'] = comments(row1[0] if row1 else [])
    from dqi_sort.sheets import read_assignments
    shared = next((x for x in reversed(S.read_csv(os.path.join(data_dir, 'sorting', 'sheets.csv'))) if x['kind'] == 'shared'), None)
    who, status = (read_assignments(sheets, shared['sheet_id']) if shared else {}).get(area, ('', ''))
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    d = wdir(data_dir, area, r['round'])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'changes.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(ch, area=area, round=r['round'], commit=r['commit'], sheet_id=r['sheet_id'], reviewer=who, status=status),
                  f, ensure_ascii=False, indent=1)
    text = report_text(area, r['round'], r['commit'], ch, talks) + f"\nReviewer: {who or '(none given)'}; status: {status or '(none)'}\n"
    with open(os.path.join(d, 'report.md'), 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    return ch


# ---------- apply ----------
def append(path, cols, rows):
    new = not os.path.exists(path)
    with open(path, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, extrasaction='ignore', lineterminator='\n')
        if new:
            w.writeheader()
        w.writerows(rows)


def fill_problems(data_dir, sessions):
    """Sessions whose talks no longer fit their length (one unit short is allowed)."""
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    assign = S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))
    rows = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    out = []
    for sid in sorted(set(sessions)):
        if sid not in rows or not sid:
            continue
        used = sum(int(talks[a['talk_id']]['minutes']) for a in assign if a['session_id'] == sid)
        cap = int(rows[sid]['minutes'])
        if used > cap or used < cap - S.UNIT_MIN:
            out.append(f'{sid}: {used} of {cap} min')
    return out


def renumber(assign, sid, order=None):
    mine = [a for a in assign.values() if a['session_id'] == sid]
    rank = {i: k for k, i in enumerate(order or [])}
    mine.sort(key=lambda a: (rank.get(a['talk_id'], len(rank)), float(a['order'] or 0)))
    for k, a in enumerate(mine, 1):
        a['order'] = k


def apply(data_dir, area):
    r = current_round(data_dir, area)
    path = os.path.join(wdir(data_dir, area, r['round']), 'changes.json')
    if not os.path.exists(path):
        sys.exit(f'run `review read` for {area} first')
    with open(path, encoding='utf-8') as f:
        ch = json.load(f)
    rpath = os.path.join(data_dir, 'sorting', 'reviews.csv')
    if any(x['area'] == area and x['round'] == str(ch['round']) for x in (S.read_csv(rpath) if os.path.exists(rpath) else [])):
        sys.exit(f'{area} round {ch["round"]} is already applied')
    if ch['missing']:
        sys.exit(f"{len(ch['missing'])} talks are missing from the sheet ({', '.join(ch['missing'][:8])}); ask the reviewer before applying")
    who = ch.get('reviewer') or reviewer(data_dir, area)
    apath = os.path.join(data_dir, 'sorting', 'assignments.csv')
    spath = os.path.join(data_dir, 'sorting', 'sessions.csv')
    assign = {a['talk_id']: a for a in S.read_csv(apath)}
    sess_rows = S.read_csv(spath)
    sessions = {s['session_id']: s for s in sess_rows}
    sent = {a['talk_id']: a for a in git_csv(data_dir, ch['commit'], 'sorting/assignments.csv')}
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    now = datetime.datetime.now().isoformat(timespec='minutes')
    why = f"review: {area} round {ch['round']}"
    moves, conflicts, touched = [], [], set()

    def still(i):           # the talk is still where the sheet found it
        return i in assign and i in sent and assign[i]['session_id'] == sent[i]['session_id'] and talks.get(i, {}).get('status') == 'active'

    def move(i, to, note=''):
        frm = assign[i]['session_id'] or 'lonely'
        touched.update({assign[i]['session_id'], to})
        assign[i].update(session_id=to, order=999, note=note)
        moves.append({'when': now[:10], 'commit': ch['commit'], 'talk_id': i, 'from': frm, 'to': to or 'lonely', 'by': who, 'reason': why})

    for c in ch['kicked']:
        if still(c['talk']):
            move(c['talk'], '', f'kicked out in {area} round {ch["round"]}')
        else:
            conflicts.append(f"{c['talk']}: ticked for the pool, but it has moved since the sheet was made")
    for c in ch['moves']:
        if not still(c['talk']) or c['to'] not in sessions:
            conflicts.append(f"{c['talk']}: moved to {c['to']}, but " + ('no such session' if c['to'] not in sessions else 'it has moved since'))
        else:
            move(c['talk'], c['to'])
    for c in ch['added']:
        i = c['talk']
        if i not in talks or talks[i]['status'] != 'active' or c['to'] not in sessions:
            conflicts.append(f"{i}: added to {c['to']}, but " + ('no such session' if c['to'] not in sessions else 'it is not an active talk'))
            continue
        frm = assign.get(i, {}).get('session_id', '')
        if i in sent and frm != sent[i]['session_id']:
            conflicts.append(f'{i}: added here, but it has moved since the sheet was made (now in {frm or "the pool"})')
            continue
        assign.setdefault(i, {'talk_id': i, 'session_id': '', 'order': '', 'locked': 'false', 'note': ''})
        move(i, c['to'], f'added in {area} round {ch["round"]}' + (f' from {frm}' if frm else ' from the pool'))
    for sid, order in ch['orders'].items():
        if sid in sessions:
            touched.add(sid)
            renumber(assign, sid, order)
    for sid in touched:
        if sid:
            renumber(assign, sid)
    for c in ch['titles']:
        sessions[c['session']]['title'] = c['to']
    for c in ch['sizes']:
        sessions[c['session']]['size'] = c['size']
    S.write_csv(apath, ['talk_id', 'session_id', 'order', 'locked', 'note'], sorted(assign.values(), key=lambda a: S.id_key(a['talk_id'])))
    S.write_csv(spath, list(sess_rows[0].keys()), sess_rows)
    if moves:
        append(os.path.join(data_dir, 'sorting', 'moves.csv'), MOVE_COLS, moves)
    notes = [{'round': ch['round'], 'area': area, 'reviewer': who, 'talk_id': c['talk'], 'session_id': c['session'],
              'note': c['note'], 'resolution': ''} for c in ch['notes']]
    if ch.get('comments'):                       # the sheet-wide comments, kept with the notes (no talk or session)
        notes.append({'round': ch['round'], 'area': area, 'reviewer': who, 'talk_id': '', 'session_id': '',
                      'note': 'Freeform comments for Claude: ' + ch['comments'], 'resolution': ''})
    if notes:
        append(os.path.join(data_dir, 'sorting', 'notes.csv'), NOTE_COLS, notes)
    n = len(moves) + len(ch['orders']) + len(ch['titles']) + len(ch['sizes']) + len(notes)
    append(rpath, REVIEW_COLS, [{'area': area, 'round': ch['round'], 'commit': ch['commit'], 'sheet_id': ch['sheet_id'],
                                 'applied': now, 'reviewer': who, 'changes': n, 'conflicts': len(conflicts)}])
    print(f"{area} round {ch['round']} applied: {len(moves)} moves, {len(ch['orders'])} reorders, {len(ch['titles'])} titles, "
          f"{len(ch['sizes'])} room sizes, {len(notes)} notes (sorting/notes.csv)")
    for c in conflicts:
        print('CONFLICT', c)
    for p in fill_problems(data_dir, touched):
        print('FILL', p)
    sent_away = [c['talk'] for c in ch['kicked'] if c['talk'] in assign and not assign[c['talk']]['session_id']]
    if sent_away:
        print('\nHomes for the talks sent to the pool (move one with `review move` if the fit is clearly good):')
        print(homes_text(data_dir, sent_away))
    return conflicts


def homes(data_dir, ids=None, k=6):
    """{talk: [(similarity, session, used, capacity, title, area out?)]}: nearest sessions, with room first."""
    from dqi_sort.pack import Space
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv')) if t['status'] == 'active'}
    assign = S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    if ids is None:
        ids = sorted((a['talk_id'] for a in assign if not a['session_id'] and a['talk_id'] in talks), key=S.id_key)
    rpath = os.path.join(data_dir, 'sorting', 'reviews.csv')
    applied = {(r['area'], r['round']) for r in S.read_csv(rpath)} if os.path.exists(rpath) else set()
    spath = os.path.join(data_dir, 'sorting', 'sheets.csv')
    latest = {r['area']: r['round'] for r in S.read_csv(spath) if r['kind'] == 'area'} if os.path.exists(spath) else {}
    out_areas = {a for a, rnd in latest.items() if (a, rnd) not in applied}
    space = Space(data_dir, talks)
    mpath = os.path.join(data_dir, 'sorting', 'moves.csv')
    left = {m['talk_id']: m['from'] for m in (S.read_csv(mpath) if os.path.exists(mpath) else []) if m['to'] == 'lonely'}
    groups = collections.defaultdict(list)
    for a in assign:
        if a['session_id'] and a['talk_id'] in talks:
            groups[a['session_id']].append(a['talk_id'])
    out = {}
    for i in ids:
        x = space.vec(i)
        if x is None:
            out[i] = []
            continue
        rows = []
        for sid, members in groups.items():
            members = [m for m in members if m != i and space.vec(m) is not None]
            if not members or sid not in sess or sid == left.get(i) or i in groups[sid]:   # not where it is, or was sent away from
                continue
            if (sess[sid]['area'] == 'VIRTUAL') != (talks[i]['track'] == 'virtual'):   # the tracks are a hard partition
                continue
            used = sum(int(talks[m]['minutes']) for m in groups[sid] if m != i)
            rows.append((float(space.centroid(members) @ x), sid, used, int(sess[sid]['minutes']), sess[sid]['title'], sess[sid]['area'] in out_areas))
        rows.sort(reverse=True)
        room = [r for r in rows if r[2] + int(talks[i]['minutes']) <= r[3]]
        out[i] = room[:k] + [r for r in rows[:k] if r not in room[:k]]
    return out


def homes_text(data_dir, ids=None):
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    lines = []
    for i, rows in homes(data_dir, ids).items():
        lines.append(f"{i} ({talks[i]['minutes']} min) {talks[i]['title'][:80]}")
        for sim, sid, used, cap, title, out in rows:
            room = 'room' if used + int(talks[i]['minutes']) <= cap else 'full'
            lines.append(f"   {sim:.3f} {sid:9s} {used:3d}/{cap} {room}{' (its area sheet is out)' if out else ''}  {title[:60]}")
    return '\n'.join(lines)


def move_one(data_dir, talk, to, reason, by='claude', position=None, force=False):
    apath = os.path.join(data_dir, 'sorting', 'assignments.csv')
    assign = {a['talk_id']: a for a in S.read_csv(apath)}
    sessions = {s['session_id'] for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    to = '' if to == 'lonely' else to
    if talk not in talks or talks[talk]['status'] != 'active':
        sys.exit(f'{talk} is not an active talk')
    if to and to not in sessions:
        sys.exit(f'no session {to}')
    if to:
        area = next(s['area'] for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv')) if s['session_id'] == to)
        if (area == 'VIRTUAL') != (talks[talk]['track'] == 'virtual'):
            sys.exit(f"{talk} is a {talks[talk]['track']} talk; {to} is in the other track (the tracks are a hard partition)")
    a = assign.setdefault(talk, {'talk_id': talk, 'session_id': '', 'order': '', 'locked': 'false', 'note': ''})
    frm = a['session_id']
    if to and to != frm and not force:           # refuse to overfill a session; make room first (or --force)
        cap = int(next(s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv')) if s['session_id'] == to)['minutes'])
        used = sum(int(talks[x['talk_id']]['minutes']) for x in assign.values() if x['session_id'] == to)
        if used + int(talks[talk]['minutes']) > cap:
            sys.exit(f'{to} is full ({used} of {cap} min); move a talk out first, or pass --force')
    a.update(session_id=to, order=(position - 0.5) if position else 999, note=reason if not to else '')
    for sid in {frm, to} - {''}:
        renumber(assign, sid)
    S.write_csv(apath, ['talk_id', 'session_id', 'order', 'locked', 'note'], sorted(assign.values(), key=lambda x: S.id_key(x['talk_id'])))
    append(os.path.join(data_dir, 'sorting', 'moves.csv'), MOVE_COLS,
           [{'when': datetime.date.today().isoformat(), 'commit': '', 'talk_id': talk, 'from': frm or 'lonely', 'to': to or 'lonely',
             'by': by, 'reason': reason}])
    print(f"{talk}: {frm or 'lonely'} -> {to or 'lonely'}")
    for p in fill_problems(data_dir, {frm, to}):
        print('FILL', p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['read', 'apply', 'move', 'homes'])
    ap.add_argument('data_dir')
    ap.add_argument('args', nargs='*', help='AREA for read and apply; TALK TO for move; talk IDs (optional) for homes')
    ap.add_argument('--reason', default='')
    ap.add_argument('--by', default='claude')
    ap.add_argument('--position', type=int)
    ap.add_argument('--force', action='store_true', help='move: allow overfilling the target session')
    a = ap.parse_args()
    if a.cmd == 'read':
        read(a.data_dir, a.args[0])
    elif a.cmd == 'apply':
        apply(a.data_dir, a.args[0])
    elif a.cmd == 'homes':
        print(homes_text(a.data_dir, a.args or None))
    else:
        if len(a.args) != 2 or not a.reason:
            sys.exit('move needs TALK TO and --reason')
        move_one(a.data_dir, a.args[0], a.args[1], a.reason, a.by, a.position, a.force)


if __name__ == '__main__':
    main()
