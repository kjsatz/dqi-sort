"""Stage 10: session chairs. Recruited by review area from the first review round, in a Chairs tab of each area's
review sheet; placed on sessions once the schedule is set.

    python -m dqi_sort.chairs sync DATA_DIR

The Chairs tab of an area sheet shows the chairs the area needs (one per session, two per virtual session; no backups)
and how many are confirmed; then the volunteers whose own talk is in the area (from the APS volunteer lists in
config.yaml `chair_volunteers`, rows of our division, people merged by email, abstracts linked by ID and by name),
with editable Status (confirmed, declined, no reply), Unavailable (e.g. Mon AM; Thu), Note and Session; then blank rows
for people from the expert's own network (name and email). Unlike the round's other tabs, the Chairs tab is updated in
place, and carried into each new round of the area's sheet, so recruiting goes on while review rounds come and go.

sync    reads every area's current Chairs tab (what people typed wins), saves it to chairs/chairs.csv, and, once
        schedule/schedule.csv exists, places each area's confirmed chairs who have no session yet, all at once: never in
        a session where they speak or at a time they present or are unavailable, and close to their own talk's topic
        where it can (a soft preference). A Check column flags a chair who presents at their session's time, chairs two
        sessions at once, or (virtual) does not present virtually. Then it rewrites the Chairs tabs in place.
        sheets sync runs the reading before it makes new rounds and the writing after, so a new round starts with the
        area's chairs. Also writes chairs/volunteers.csv.
"""
import argparse, collections, json, os, re, sys
from dqi_sort import sessions as S

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
TAB = 'Chairs'
COLS = ['Volunteer', 'Email', 'Affiliation', 'Can chair', 'Chaired before', 'Their talks', 'Match note', 'Status', 'Unavailable',
        'Note', 'Session', 'Check']
EDIT = [7, 8, 9, 10]                       # Status, Unavailable, Note, Session
NEW_ROWS = 8                               # blank rows for people from the expert's own network
ENTRY = ['area', 'name', 'email', 'status', 'unavailable', 'note', 'session', 'check']


def col(row, *names):
    for k in row:
        low = re.sub(r'\s+', ' ', k).strip().lower()
        if any(low.startswith(n) for n in names):
            return (row[k] or '').strip()
    return ''


def norm(name):
    return re.sub(r'[^a-z]', '', name.lower())


# ---------- volunteers ----------
def volunteers(data_dir, cfg, talks):
    files = cfg.get('chair_volunteers') or {}
    code = str(cfg.get('division_code', ''))
    people = collections.OrderedDict()
    for mode_file in ('in_person', 'virtual'):
        path = files.get(mode_file)
        if not path:
            continue
        import csv
        with open(os.path.join(data_dir, path), encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                if not col(r, 'sub-category').startswith(code):
                    continue
                email = col(r, 'email').lower()
                name = f"{col(r, 'first name')} {col(r, 'last name')}".strip()
                key = email or norm(name)
                p = people.setdefault(key, {'name': name, 'email': email, 'affiliation': col(r, 'affiliation'), 'chair_mode': set(),
                                            'presenting': set(), 'chaired_before': '', 'talk_ids': [], 'lists': set(), 'note': []})
                p['lists'].add(mode_file)
                m = col(r, 'chairing method').lower()
                p['chair_mode'] |= {'in_person', 'virtual'} if m.startswith('both') else ({'virtual'} if m.startswith('virtual') else {'in_person'})
                pm = col(r, "speaker's presentation", 'speaker').lower()
                p['presenting'].add('virtual' if pm.startswith('virtual') else 'in_person')
                p['chaired_before'] = p['chaired_before'] or col(r, 'have you session chaired')
                i = col(r, 'id')
                if i and i not in p['talk_ids']:
                    p['talk_ids'].append(i)
    by_name = collections.defaultdict(list)
    for t in talks.values():
        if t['status'] == 'active':
            by_name[norm(t['speaker'])].append(t['talk_id'])
    out = []
    for n, p in enumerate(people.values(), 1):
        extra = [i for i in by_name.get(norm(p['name']), []) if i not in p['talk_ids']]
        if extra:
            p['note'].append(f"also speaker of {', '.join(extra)} by name (confirm)")
            p['talk_ids'] += extra
        missing = [i for i in p['talk_ids'] if i not in talks or talks[i]['status'] != 'active']
        if missing:
            p['note'].append(f"abstract {', '.join(missing)} is not in our contributed program (a symposium talk, or moved to another unit)")
        mode = 'both' if p['chair_mode'] == {'in_person', 'virtual'} else next(iter(p['chair_mode']))
        out.append({'volunteer_id': f'V{n:03d}', 'name': p['name'], 'email': p['email'], 'affiliation': p['affiliation'],
                    'chair_mode': mode, 'presenting_mode': '/'.join(sorted(p['presenting'])), 'chaired_before': p['chaired_before'],
                    'talk_ids': ';'.join(p['talk_ids']), 'match_note': '; '.join(p['note'])})
    return out


def unavailable(text, day, start):
    """True if "Mon AM; Thu" (days or half-days) covers a session on this day starting at this time."""
    for part in re.split(r'[;,]', text or ''):
        m = re.search(r'\b(mon|tue|wed|thu|fri)[a-z]*\b\s*(am|pm)?', part, re.I)
        if m and m.group(1)[:3].title() == day:
            half = (m.group(2) or '').lower()
            if not half or (half == 'am') == (start < '12:00'):
                return True
    return False


def need(area, sessions_in_area):
    return (2 if area == 'VIRTUAL' else 1) * len(sessions_in_area)


def read_tab(sheets, sid):
    """{(name, email): {status, unavailable, note, session}} typed in a sheet's Chairs tab (None if it has none)."""
    try:
        vals = sheets.spreadsheets().values().get(spreadsheetId=sid, range=f"'{TAB}'!A2:L2000").execute(num_retries=5).get('values', [])
    except Exception:
        return None
    if not vals or vals[0][:1] != ['Volunteer']:
        return None
    out = {}
    for r in vals[1:]:
        r = r + [''] * 12
        if r[0].strip():
            out[(r[0].strip(), r[1].strip().lower())] = {'status': r[7].strip().lower(), 'unavailable': r[8].strip(),
                                                         'note': r[9].strip(), 'session': r[10].strip()}
    return out


def context(data_dir):
    cfg = S.load_config(data_dir)
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    assign = {a['talk_id']: a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))}
    sched = {}
    p = os.path.join(data_dir, 'schedule', 'schedule.csv')
    if os.path.exists(p):
        slots = {s['slot_id']: s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
        sched = {r['session_id']: slots[r['slot_id']] for r in S.read_csv(p) if r['slot_id'] in slots}
    vols = volunteers(data_dir, cfg, talks)
    for v in vols:
        own = [assign.get(i, '') for i in v['talk_ids'].split(';') if i]
        v['own_sessions'] = ';'.join(x for x in own if x)
        v['area'] = next((sess[x]['area'] for x in own if x in sess), '')
    return cfg, talks, sess, assign, sched, vols


def current_sheets(data_dir):
    log = S.read_csv(os.path.join(data_dir, 'sorting', 'sheets.csv')) if os.path.exists(os.path.join(data_dir, 'sorting', 'sheets.csv')) else []
    latest = {}
    for r in log:
        if r['kind'] == 'area':
            latest[r['area']] = r
    return latest


def load_entries(data_dir):
    p = os.path.join(data_dir, 'chairs', 'chairs.csv')
    rows = S.read_csv(p) if os.path.exists(p) and 'name' in (open(p).readline()) else []
    return {(r['area'], r['name'], r['email']): r for r in rows}


def collect(data_dir, sheets):
    """Read every area's current Chairs tab into chairs/chairs.csv (the sheets win over the saved copy)."""
    entries = load_entries(data_dir)
    for area, r in current_sheets(data_dir).items():
        typed = read_tab(sheets, r['sheet_id'])
        if typed is None:                        # no Chairs tab yet: keep the saved copy
            continue
        entries = {k: e for k, e in entries.items() if k[0] != area}    # the tab is the whole truth (rows deleted there go)
        for (name, email), e in typed.items():
            entries[(area, name, email)] = dict(area=area, name=name, email=email, **e)
    save(data_dir, entries)
    return entries


def save(data_dir, entries):
    os.makedirs(os.path.join(data_dir, 'chairs'), exist_ok=True)
    S.write_csv(os.path.join(data_dir, 'chairs', 'chairs.csv'), ENTRY,
                sorted(({k: e.get(k, '') for k in ENTRY} for e in entries.values()), key=lambda e: (e['area'], e['name'])))


def presenters(vols, talks, assign, sched):
    out = collections.defaultdict(set)
    for v in vols:
        for x in v['own_sessions'].split(';'):
            if x in sched:
                out[v['email']].add((sched[x]['day'], sched[x]['start'])); out[norm(v['name'])].add((sched[x]['day'], sched[x]['start']))
    for i, t in talks.items():
        if t['status'] == 'active' and assign.get(i) in sched:
            out[norm(t['speaker'])].add((sched[assign[i]]['day'], sched[assign[i]]['start']))
    return out


def place(entries, vols, sess, sched, assign, talks, presents, data_dir):
    """Place each area's confirmed chairs with no session, all at once (an assignment solver): never in a session where
    they speak or at a time they present or are unavailable; then the best topical fit to their own talk (soft)."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    from dqi_sort.pack import Space
    by_key = {(v['name'], v['email']): v for v in vols}
    active = {i: t for i, t in talks.items() if t['status'] == 'active'}
    members = collections.defaultdict(list)
    for i, a in assign.items():
        if a and i in active:
            members[a].append(i)
    space, notes = None, []
    for area in sorted({e['area'] for e in entries.values()}):
        mine = [x for x in sess if sess[x]['area'] == area and x in sched]
        per = 2 if area == 'VIRTUAL' else 1
        filled = collections.Counter(e['session'] for e in entries.values() if e['area'] == area and e.get('session') and e.get('status') == 'confirmed')
        slots = [x for x in mine for _ in range(per - filled[x])]
        chairs = [k for k, e in entries.items() if e['area'] == area and e.get('status') == 'confirmed' and not e.get('session')]
        if not chairs:
            continue
        if not slots:
            notes += [f'{k[1]}: every session in {area} has its chairs' for k in chairs]; continue
        cost = np.full((len(chairs), len(slots)), 1e6)
        for r, k in enumerate(chairs):
            v = by_key.get((k[1], k[2]), {})
            own = [i for i in (v.get('talk_ids') or '').split(';') if i in active]
            busy = presents.get(k[2], set()) | presents.get(norm(k[1]), set())
            speaks = {assign.get(i) for i in own}
            vecs = []
            if own:
                space = space or Space(data_dir, active)
                vecs = [space.vec(i) for i in own if space.vec(i) is not None]
            x0 = np.mean(vecs, axis=0) if vecs else None
            for c, x in enumerate(slots):
                t = (sched[x]['day'], sched[x]['start'])
                if x in speaks or t in busy or unavailable(entries[k].get('unavailable'), *t):
                    continue
                cost[r, c] = -float(space.centroid(members[x]) @ x0) if x0 is not None else 0.0
        rows, cols = linear_sum_assignment(cost)
        for r, c in zip(rows, cols):
            if cost[r, c] < 1e6:
                entries[chairs[r]]['session'] = slots[c]
                entries[chairs[r]]['note'] = (entries[chairs[r]].get('note') or '') or 'placed by Claude (no clash; close topic where possible)'
            else:
                notes.append(f'{chairs[r][1]}: no session in {area} without a clash')
        notes += [f'{chairs[r][1]}: more confirmed chairs than sessions in {area}' for r in range(len(chairs)) if r not in set(rows)]
    for n in notes:
        print('PLACE', n)
    return notes


def checks(entries, vols, sess, sched, presents):
    virtual_people = {v['email'] for v in vols if 'virtual' in v['presenting_mode']} | {norm(v['name']) for v in vols if 'virtual' in v['presenting_mode']}
    at = collections.defaultdict(list)
    for k, e in entries.items():
        if e.get('session') in sched and e.get('status') == 'confirmed':
            at[e['email'] or norm(e['name'])].append((sched[e['session']]['day'], sched[e['session']]['start']))
    for k, e in entries.items():
        x, c = e.get('session'), []
        if x:
            if x not in sess:
                c.append(f'no session {x}')
            elif sess[x]['area'] != e['area']:
                c.append(f'{x} is in {sess[x]["area"]}')
            if x in sched:
                t = (sched[x]['day'], sched[x]['start'])
                if t in presents.get(e['email'], set()) | presents.get(norm(e['name']), set()):
                    c.append('presents at this time')
                if at[e['email'] or norm(e['name'])].count(t) > 1:
                    c.append('chairs two sessions at this time')
                if sess.get(x, {}).get('area') == 'VIRTUAL' and not ({e['email'], norm(e['name'])} & virtual_people):
                    c.append('not a virtual presenter (fine if they agree)')
        e['check'] = '; '.join(c)


def tab_rows(area, vols, entries, sess, sched):
    when = lambda x: f"{x} ({sched[x]['day']} {sched[x]['start']})" if x in sched else x
    mine = sorted((v for v in vols if v['area'] == area), key=lambda v: v['name'])
    known = {(v['name'], v['email']) for v in mine}
    rows = []
    for v in mine:
        e = entries.get((area, v['name'], v['email']), {})
        rows.append([v['name'], v['email'], v['affiliation'], v['chair_mode'].replace('_', '-'), v['chaired_before'],
                     '; '.join(when(x) for x in v['own_sessions'].split(';') if x), v['match_note'],
                     e.get('status', ''), e.get('unavailable', ''), e.get('note', ''), e.get('session', ''), e.get('check', '')])
    for (a, n, m), e in sorted(entries.items()):
        if a == area and (n, m) not in known:
            rows.append([n, m, '', '', '', '', 'added by the area', e.get('status', ''), e.get('unavailable', ''), e.get('note', ''),
                         e.get('session', ''), e.get('check', '')])
    rows += [[''] * 12 for _ in range(NEW_ROWS)]
    n_need = need(area, [x for x in sess if sess[x]['area'] == area])
    n_conf = sum(1 for (a, _, _), e in entries.items() if a == area and e.get('status') == 'confirmed')
    return rows, n_need, n_conf


def chairs_book(area, rows, n_need, n_conf, placed):
    from dqi_sort.sheets import Book, tab_requests, color_req, HEADER_ROW, NOTES
    b = Book(f"{area} chairs: {n_need} needed (one per session" + (', two per virtual session' if area == 'VIRTUAL' else '') +
             f"; no backups); {n_conf} confirmed" + (f'; {placed} placed on sessions' if placed else '') +
             '. Set Status to confirmed; sessions are assigned after scheduling (or type one in Session).')

    def fmt(sid, n):
        reqs = tab_requests(sid, n, [170, 210, 200, 80, 70, 170, 200, 90, 110, 200, 130, 220], wrap_cols=[2, 5, 6, 9, 11])
        reqs += [color_req(sid, HEADER_ROW, HEADER_ROW + n, c, c + 1, NOTES) for c in EDIT]
        reqs.append(color_req(sid, HEADER_ROW + n - NEW_ROWS, HEADER_ROW + n, 0, 2, NOTES))
        reqs.append({'setDataValidation': {'range': {'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n, 'startColumnIndex': 7, 'endColumnIndex': 8},
                                           'rule': {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': v} for v in ('confirmed', 'declined', 'no reply')]},
                                                    'showCustomUi': True, 'strict': False}}})
        free = [{'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n, 'startColumnIndex': c, 'endColumnIndex': c + 1} for c in EDIT]
        free.append({'sheetId': sid, 'startRowIndex': HEADER_ROW + n - NEW_ROWS, 'endRowIndex': HEADER_ROW + n, 'startColumnIndex': 0, 'endColumnIndex': 2})
        return reqs + [{'addProtectedRange': {'protectedRange': {'range': {'sheetId': sid}, 'unprotectedRanges': free, 'warningOnly': False,
                                                                 'description': 'Generated by dqi_sort.chairs'}}}]
    b.tab(TAB, COLS, rows, fmt)
    return b


def publish(data_dir, sheets, entries, areas=None):
    """Rewrite the Chairs tab in each area's current sheet (in place), from the entries."""
    cfg, talks, sess, assign, sched, vols = context(data_dir)
    counts = {}
    for area, r in sorted(current_sheets(data_dir).items()):
        rows, n_need, n_conf = tab_rows(area, vols, entries, sess, sched)
        placed = sum(1 for (a, _, _), e in entries.items() if a == area and e.get('session'))
        counts[area] = (n_need, n_conf)
        if areas is None or area in areas:
            chairs_book(area, rows, n_need, n_conf, placed).write(sheets, r['sheet_id'], False)
            meta = sheets.spreadsheets().get(spreadsheetId=r['sheet_id'], fields='sheets(properties(sheetId,title))').execute(num_retries=5)
            tabs = [x['properties'] for x in meta['sheets']]
            sid = next(t['sheetId'] for t in tabs if t['title'] == TAB)
            sheets.spreadsheets().batchUpdate(spreadsheetId=r['sheet_id'], body={'requests': [{'updateSheetProperties': {
                'properties': {'sheetId': sid, 'index': len(tabs)}, 'fields': 'index'}}]}).execute(num_retries=5)   # last tab
    return counts


def retire(data_dir, sheets, areas):
    """After a new round, replace the previous rounds' Chairs tabs with a locked pointer to the current sheet."""
    from dqi_sort.sheets import Book, tab_requests, protect_req
    log = S.read_csv(os.path.join(data_dir, 'sorting', 'sheets.csv'))
    cur = current_sheets(data_dir)
    for area in areas:
        for r in log:
            if r['kind'] == 'area' and r['area'] == area and r['sheet_id'] != cur[area]['sheet_id']:
                try:
                    meta = sheets.spreadsheets().get(spreadsheetId=r['sheet_id'], fields='sheets(properties(title))').execute(num_retries=5)
                except Exception:
                    continue
                if TAB not in [m['properties']['title'] for m in meta['sheets']]:
                    continue
                b = Book(f"{area} chairs have moved to round {cur[area]['round']}.")
                b.tab(TAB, ['Go to'], [[f'=HYPERLINK("{cur[area]["url"]}", "{area} round {cur[area]["round"]}: Chairs tab")']],
                      lambda sid, n: tab_requests(sid, n, [400]) + protect_req(sid))
                b.write(sheets, r['sheet_id'], False)


def sync(data_dir):
    from dqi_sort import gsheets
    _, sheets = gsheets.services()
    cfg, talks, sess, assign, sched, vols = context(data_dir)
    entries = collect(data_dir, sheets)
    for v in vols:                                # every volunteer has a row, even before anyone types anything
        if v['area']:
            entries.setdefault((v['area'], v['name'], v['email']), {'area': v['area'], 'name': v['name'], 'email': v['email']})
    if sched:
        presents = presenters(vols, talks, assign, sched)
        place(entries, vols, sess, sched, assign, talks, presents, data_dir)
        checks(entries, vols, sess, sched, presents)
    save(data_dir, {k: e for k, e in entries.items() if any(e.get(f) for f in ('status', 'unavailable', 'note', 'session'))})
    counts = publish(data_dir, sheets, entries)
    S.write_csv(os.path.join(data_dir, 'chairs', 'volunteers.csv'),
                ['volunteer_id', 'name', 'email', 'affiliation', 'chair_mode', 'presenting_mode', 'chaired_before', 'talk_ids',
                 'own_sessions', 'area', 'match_note'], vols)
    print(f"{len(vols)} volunteers; chairs needed {sum(n for n, _ in counts.values())}, confirmed {sum(c for _, c in counts.values())}; "
          f"{sum(1 for e in entries.values() if e.get('session'))} placed; {sum(1 for e in entries.values() if e.get('check'))} flagged")
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['sync'])
    ap.add_argument('data_dir')
    a = ap.parse_args()
    sync(a.data_dir)


if __name__ == '__main__':
    main()
