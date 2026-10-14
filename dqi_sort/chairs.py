"""Stage 10: session chairs, recruited in one spreadsheet (a tab per review area), from the first review round.

    python -m dqi_sort.chairs sync DATA_DIR

sync  makes the recruiting spreadsheet the first time (in the review folder), then updates it in place, keeping
      everything people typed. Tabs:
      - Overview: one row per review area, with Responsible (the subject-matter expert recruiting for it; pre-filled
        with its reviewer) and Status, both editable, and the chairs needed (one per session, two per virtual session;
        no backups), confirmed and placed.
      - One tab per area: its volunteers (APS lists in config.yaml `chair_volunteers`, rows of our division, people
        merged by email, abstracts linked by ID and by name) with their talks, and editable Abstract ID (pre-filled
        for volunteers; for someone added, filled in if they can find it, so their talks count in the clash check),
        Emailed? and Confirmed? (checkboxes), Availability (free text: "Mon AM; not Thursday afternoon"), Notes (free
        text: wishes, a decline, anything Claude should know when placing) and Session; blank rows for people from the
        expert's network; once scheduled, the sessions still needing a chair.
      - Other volunteers (abstract not in our program), and Instructions (how to fill it in, diversity, the invitation).
      Once schedule/schedule.csv exists it places each area's confirmed chairs who have no session, all at once: never
      in a session where they speak or at a time they present or are unavailable, and close to their own talk's topic
      where it can. Claude reads the Notes first and types a Session for anyone whose wishes need it. A Check column
      shows how Availability was read and flags problems (presents at that time, two sessions at once, not a virtual
      presenter for a virtual session). Saves chairs/chairs.csv, chairs/area_status.csv and chairs/volunteers.csv.
"""
import argparse, collections, json, os, re, sys
from dqi_sort import sessions as S

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
NOTE_COL = 'Abstract note (Claude)'
CHECK_COL = 'Claude check: availability as read, clashes'
COLS = ['Volunteer', 'Email', 'Affiliation', 'Abstract ID', 'Their talks', NOTE_COL, 'Emailed?', 'Confirmed?', 'Availability', 'Notes',
        'Session', CHECK_COL]
NC = len(COLS)
EDIT = [3, 6, 7, 8, 9, 10]                 # Abstract ID, Emailed?, Confirmed?, Availability, Notes, Session
BOXES = [6, 7]                             # Emailed?, Confirmed? as checkboxes
READ = {'name': ['Volunteer'], 'email': ['Email'], 'abstract_id': ['Abstract ID'], 'emailed': ['Emailed?'],   # fields by header:
        'confirmed': ['Confirmed?'], 'availability': ['Availability'], 'notes': ['Notes'], 'session': ['Session']}  # renames keep working
NEW_ROWS = 25                              # blank rows for people from the expert's own network
NEEDING = 'Sessions still needing a chair'
ENTRY = ['area', 'name', 'email', 'abstract_id', 'emailed', 'confirmed', 'availability', 'notes', 'session', 'check']
SUBJECT = 'Session chair for DQI at the Global Physics Summit'
TEMPLATE = """Dear {name},

We are working on scheduling the Global Physics Summit ({dates}) and need volunteer session chairs in {topic} for the Division of Quantum Information. If you're available, please reply with any schedule constraints or requests. The sessions are being scheduled soon, and we won't schedule anything in conflict with your talk. If possible, please get back to me within 72 hours to facilitate scheduling. Thank you for considering volunteering!

Best,
{requester}"""


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
    """True if free text such as "Mon AM; not Thursday afternoon; Fri" rules out a session on this day at this time."""
    for part in re.split(r'[;,]|\band\b', text or '', flags=re.I):
        for m in re.finditer(r'\b(mon|tue|wed|thu|fri)[a-z]*\b\s*(am|pm|morning|afternoon)?', part, re.I):
            if m.group(1)[:3].title() != day:
                continue
            half = (m.group(2) or '').lower()
            if not half or (half in ('am', 'morning')) == (start < '12:00'):
                return True
    return False


def reading(text):
    """How the availability text was read, for the Check column."""
    out = []
    for d in DAYS:
        am, pm = unavailable(text, d, '08:00'), unavailable(text, d, '13:30')
        if am and pm:
            out.append(d)
        elif am or pm:
            out.append(f"{d} {'AM' if am else 'PM'}")
    return ('read as unavailable: ' + ', '.join(out)) if out else ''


def yes(x):
    return str(x).strip().upper() in ('TRUE', 'YES', 'Y', 'X', '1')


def own_talks(e, by_key, talks):
    """A chair's own active talks: a volunteer's linked abstracts, or the Abstract ID typed for someone added."""
    v = by_key.get((e.get('name'), e.get('email')), {})
    ids = [i for i in re.split(r'[;,\s]+', (v.get('talk_ids') or '') + ';' + (e.get('abstract_id') or '')) if i]
    return [i for i in dict.fromkeys(ids) if i in talks and talks[i]['status'] == 'active']


def need(area, sessions_in_area):
    return (2 if area == 'VIRTUAL' else 1) * len(sessions_in_area)


def topic(area, cfg):
    """The area's broad topic for the invitation: its name up to any colon, in lower case."""
    name = ((cfg.get('areas') or {}).get(area) or {}).get('name', area)
    return 'the virtual conference' if area == 'VIRTUAL' else name.split(':')[0].strip().lower()


def context(data_dir):
    cfg = S.load_config(data_dir)
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    assign = {a['talk_id']: a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))}
    sched, slots = {}, {}
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


def load_entries(data_dir):
    p = os.path.join(data_dir, 'chairs', 'chairs.csv')
    rows = S.read_csv(p) if os.path.exists(p) else []
    return {(r['area'], r['name'], r['email']): r for r in rows if 'name' in r and 'availability' in r}


def save(data_dir, entries):
    os.makedirs(os.path.join(data_dir, 'chairs'), exist_ok=True)
    S.write_csv(os.path.join(data_dir, 'chairs', 'chairs.csv'), ENTRY,
                sorted(({k: e.get(k, '') for k in ENTRY} for e in entries.values()), key=lambda e: (e['area'], e['name'])))


def read_back(sheets, sid, areas):
    """What people typed: ({(area, name, email): entry} for tabs that exist, {area: (responsible, status)})."""
    entries, overview, seen = {}, {}, set()
    try:
        meta = sheets.spreadsheets().get(spreadsheetId=sid, fields='sheets(properties(title))').execute(num_retries=5)
    except Exception:
        return None, {}
    titles = [x['properties']['title'] for x in meta['sheets']]
    for t in titles:
        if t != 'Overview' and t not in areas:
            continue
        vals = sheets.spreadsheets().values().get(spreadsheetId=sid, range=f"'{t}'!A2:N2000").execute(num_retries=5).get('values', [])
        if t == 'Overview':
            for r in vals[1:]:
                r = r + [''] * 8
                if r[0]:
                    overview[r[0]] = (r[2].strip(), r[7].strip())
            continue
        head = [h.strip() for h in (vals[0] if vals else [])]
        at = {f: next((head.index(h) for h in names if h in head), None) for f, names in READ.items()}
        if at['name'] is None or at['email'] is None:
            print(f'{t}: no Volunteer and Email columns; its entries are not read')
            continue
        seen.add(t)
        for r in vals[1:]:
            get = lambda f: (r[at[f]] if at[f] is not None and at[f] < len(r) else '').strip()
            if get('name') == NEEDING or (r and r[0] == NEEDING):
                break
            if get('name'):
                entries[(t, get('name'), get('email').lower())] = {
                    'area': t, 'name': get('name'), 'email': get('email').lower(),
                    'abstract_id': ', '.join(re.findall(r'\d{5,}', get('abstract_id'))),
                    'emailed': 'TRUE' if yes(get('emailed')) else '', 'confirmed': 'TRUE' if yes(get('confirmed')) else '',
                    'availability': get('availability'), 'notes': get('notes'), 'session': get('session')}
    return (entries, seen), overview


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
        filled = collections.Counter(e['session'] for e in entries.values() if e['area'] == area and e.get('session') and yes(e.get('confirmed')))
        slots = [x for x in mine for _ in range(per - filled[x])]
        chairs = [k for k, e in entries.items() if e['area'] == area and yes(e.get('confirmed')) and not e.get('session')]
        if not chairs:
            continue
        if not slots:
            notes += [f'{k[1]}: every session in {area} has its chairs' for k in chairs]; continue
        cost = np.full((len(chairs), len(slots)), 1e6)
        for r, k in enumerate(chairs):
            own = own_talks(entries[k], by_key, talks)
            busy = presents.get(k[2], set()) | presents.get(norm(k[1]), set())
            speaks = {assign.get(i) for i in own}
            vecs = []
            if own:
                space = space or Space(data_dir, active)
                vecs = [space.vec(i) for i in own if space.vec(i) is not None]
            x0 = np.mean(vecs, axis=0) if vecs else None
            for c, x in enumerate(slots):
                t = (sched[x]['day'], sched[x]['start'])
                if x in speaks or t in busy or unavailable(entries[k].get('availability'), *t):
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
        if e.get('session') in sched and yes(e.get('confirmed')):
            at[e['email'] or norm(e['name'])].append((sched[e['session']]['day'], sched[e['session']]['start']))
    for k, e in entries.items():
        x, c = e.get('session'), [reading(e.get('availability'))] if e.get('availability') else []
        if x:
            if x not in sess:
                c.append(f'no session {x}')
            elif sess[x]['area'] != e['area']:
                c.append(f'{x} is in {sess[x]["area"]}')
            if x in sched:
                t = (sched[x]['day'], sched[x]['start'])
                if t in presents.get(e['email'], set()) | presents.get(norm(e['name']), set()):
                    c.append('presents at this time')
                if unavailable(e.get('availability'), *t):
                    c.append('unavailable at this time')
                if at[e['email'] or norm(e['name'])].count(t) > 1:
                    c.append('chairs two sessions at this time')
                if sess.get(x, {}).get('area') == 'VIRTUAL' and not ({e['email'], norm(e['name'])} & virtual_people):
                    c.append('not a virtual presenter (fine if they agree)')
        e['check'] = '; '.join(x for x in c if x)


def area_rows(area, vols, entries, sess, sched, assign_of=None):
    assign_of = assign_of or {}
    when = lambda x: f"{x} ({sched[x]['day']} {sched[x]['start']})" if x in sched else x
    mine = sorted((v for v in vols if v['area'] == area), key=lambda v: v['name'])
    known = {(v['name'], v['email']) for v in mine}
    rows = []
    for v in mine:
        e = entries.get((area, v['name'], v['email']), {})
        rows.append([v['name'], v['email'], v['affiliation'], e.get('abstract_id') or v['talk_ids'].replace(';', ', '),
                     '; '.join(when(x) for x in v['own_sessions'].split(';') if x), v['match_note'],
                     yes(e.get('emailed')), yes(e.get('confirmed')), e.get('availability', ''), e.get('notes', ''), e.get('session', ''), e.get('check', '')])
    for (a, n, m), e in sorted(entries.items()):
        if a == area and (n, m) not in known:
            theirs = [assign_of.get(i, '') for i in re.split(r'[;,\s]+', e.get('abstract_id') or '') if i]
            rows.append([n, m, '', e.get('abstract_id', ''), '; '.join(when(x) for x in theirs if x), 'added by the area',
                         yes(e.get('emailed')), yes(e.get('confirmed')), e.get('availability', ''), e.get('notes', ''),
                         e.get('session', ''), e.get('check', '')])
    n_people = len(rows)
    rows += [[''] * 6 + [False, False] + [''] * 4 for _ in range(NEW_ROWS)]
    mine_s = sorted((x for x in sess if sess[x]['area'] == area), key=lambda x: (DAYS.index(sched[x]['day']), sched[x]['start']) if x in sched else (9, x))
    per = 2 if area == 'VIRTUAL' else 1
    if sched:
        got = collections.Counter(e['session'] for e in entries.values() if e['area'] == area and e.get('session') and yes(e.get('confirmed')))
        open_ = [x for x in mine_s if got[x] < per]
        rows += [[''] * NC, [NEEDING, 'Title', 'When', 'Chairs still needed'] + [''] * (NC - 4)]
        rows += [[x, sess[x]['title'], f"{sched[x]['day']} {sched[x]['start']}" if x in sched else '', per - got[x]] + [''] * (NC - 4) for x in open_]
    return rows, n_people


def book(cfg, areas, tabs, overview, reviewers, counts, others, name_of):
    from dqi_sort.sheets import Book, tab_requests, protect_req, color_req, HEADER_ROW, NOTES
    title = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    b = Book(f'{title}: session chair recruiting. One tab per review area; edit the tinted cells. See Instructions.')
    orows = []
    for a in areas:
        n_need, n_people, placed = counts[a]
        resp, stat = overview.get(a, (reviewers.get(a, ''), ''))
        conf = f"=COUNTIF('{a}'!H{HEADER_ROW + 1}:H{HEADER_ROW + n_people + NEW_ROWS},TRUE)"
        orows.append([a, name_of(a), resp, n_need, conf, placed, topic(a, cfg), stat])
    b.tab('Overview', ['Area', 'Name', 'Responsible', 'Chairs needed', 'Confirmed', 'Placed on sessions', 'Topic in the invitation', 'Status'], orows,
          lambda sid, n: tab_requests(sid, n, [80, 320, 200, 100, 90, 110, 220, 320], wrap_cols=[1, 7], notes_cols=[2, 7]) + protect_req(sid, n, [2, 7]))
    for a in areas:
        rows, n_people = tabs[a]

        def fmt(sid, n, n_people=n_people):
            people = n_people + NEW_ROWS
            reqs = tab_requests(sid, n, [170, 210, 200, 90, 170, 200, 75, 85, 170, 320, 110, 240], wrap_cols=[2, 3, 4, 5, 8, 9, 11])
            reqs += [color_req(sid, HEADER_ROW, HEADER_ROW + people, c, c + 1, NOTES) for c in EDIT]
            reqs.append(color_req(sid, HEADER_ROW + n_people, HEADER_ROW + people, 0, 2, NOTES))
            reqs.append({'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': HEADER_ROW + people + 1, 'endRowIndex': HEADER_ROW + people + 2},
                                        'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}})
            reqs += [{'setDataValidation': {'range': {'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + people,
                                                      'startColumnIndex': c, 'endColumnIndex': c + 1},
                                            'rule': {'condition': {'type': 'BOOLEAN'}}}} for c in BOXES]
            free = [{'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + people, 'startColumnIndex': c, 'endColumnIndex': c + 1} for c in EDIT]
            free.append({'sheetId': sid, 'startRowIndex': HEADER_ROW + n_people, 'endRowIndex': HEADER_ROW + people, 'startColumnIndex': 0, 'endColumnIndex': 2})
            return reqs + [{'addProtectedRange': {'protectedRange': {'range': {'sheetId': sid}, 'unprotectedRanges': free, 'warningOnly': False,
                                                                     'description': 'Generated by dqi_sort.chairs'}}}]
        b.tab(a, COLS, rows, fmt)
    b.tab('Other volunteers', ['Volunteer', 'Email', 'Affiliation', NOTE_COL],
          [[v['name'], v['email'], v['affiliation'], v['match_note']] for v in others],
          lambda sid, n: tab_requests(sid, n, [180, 220, 240, 420], wrap_cols=[2, 3]) + protect_req(sid))
    how = instructions(cfg)
    b.tab('Instructions', how[0], how[1:], lambda sid, n: tab_requests(sid, n, [190, 760], wrap_cols=[1]) + protect_req(sid))
    return b


def instructions(cfg):
    dates = cfg.get('meeting_dates', 'April 11-16, 2027')
    return [['Topic', 'What to do'],
            ['Your area', 'Each review area has a tab, listing the volunteers whose own talk is in that area. The area needs one confirmed chair '
                          'per session (two per virtual session); there are no backups. The Overview shows how many are needed and confirmed.'],
            ['Diversity', 'Strive for a diverse set of chairs in terms of career stage, institution, and demographics.'],
            ['Inviting', 'Write to volunteers (or anyone from your own network) with the invitation below. Add people who are not listed in '
                         'the blank rows under the volunteers: name and email in the first two columns.'],
            ['Emailed? / Confirmed?', 'Tick Emailed? when you have written to them, and Confirmed? when they agree. A decline goes in Notes.'],
            ['Abstract ID', 'Filled in for the listed volunteers. For someone you add, enter their abstract ID if they can find it '
                            '(it is in their APS confirmation); then their talk is taken into account so they are never placed against it. '
                            'Leave it blank if they have no talk or cannot find it.'],
            ['Availability', 'In plain words, when they cannot chair: e.g. "Mon AM; not Thursday afternoon". The Check column shows how it was read.'],
            ['Notes', 'Anything useful, in free text: a topic they would like, a preferred day, someone to co-chair with. Claude reads these when '
                      'placing chairs on sessions.'],
            ['Session', 'Leave blank: once the schedule is set, Claude places each confirmed chair on a session in your area where they do not '
                        'speak and that does not clash with their talks or availability, close to their own topic where it can. Or type a '
                        'session code yourself.'],
            [NOTE_COL, 'Filled in by Claude from the APS lists: another talk found under the same name (to confirm), or an abstract '
                       'that is not in our program.'],
            [CHECK_COL, 'Filled in by Claude: how Availability was read, and any problem with a placement (presents at that time, '
                        'two sessions at once, not a virtual presenter for a virtual session).'],
            ['Invitation', f'Subject: {SUBJECT}\n\n' + TEMPLATE.format(name='<name>', dates=dates, topic='<the topic in the Overview>', requester='<your name>')]]


def sync(data_dir):
    from dqi_sort import gsheets
    from dqi_sort.sheets import LOG_COLS
    cfg, talks, sess, assign, sched, vols = context(data_dir)
    names = {a: v.get('name', '') for a, v in (cfg.get('areas') or {}).items()}
    areas = sorted({s['area'] for s in sess.values()}, key=lambda a: (a == 'VIRTUAL', a))
    rpath = os.path.join(data_dir, 'sorting', 'area_status.csv')
    reviewers = {r['area']: r['responsible'] for r in S.read_csv(rpath)} if os.path.exists(rpath) else {}
    log_path = os.path.join(data_dir, 'sorting', 'sheets.csv')
    log = S.read_csv(log_path) if os.path.exists(log_path) else []
    row = next((r for r in reversed(log) if r['kind'] == 'recruiting'), None)
    drive, sheets = gsheets.services()
    entries, overview = load_entries(data_dir), {}
    if row:
        got, overview = read_back(sheets, row['sheet_id'], areas)
        if got:
            typed, seen = got
            entries = {k: e for k, e in entries.items() if k[0] not in seen}      # each tab is the whole truth for its area
            entries.update(typed)
    if sched:
        presents = presenters(vols, talks, assign, sched)
        by_key = {(v['name'], v['email']): v for v in vols}
        for e in entries.values():                # someone added with an Abstract ID: their talks count too
            for i in own_talks(e, by_key, talks):
                if assign.get(i) in sched:
                    t = (sched[assign[i]]['day'], sched[assign[i]]['start'])
                    presents[e['email']].add(t); presents[norm(e['name'])].add(t)
        place(entries, vols, sess, sched, assign, talks, presents, data_dir)
    else:
        presents = {}
    checks(entries, vols, sess, sched, presents)
    tabs, counts = {}, {}
    for a in areas:
        rows, n_people = area_rows(a, vols, entries, sess, sched, assign)
        tabs[a] = (rows, n_people)
        counts[a] = (need(a, [x for x in sess if sess[x]['area'] == a]), n_people,
                     sum(1 for e in entries.values() if e['area'] == a and e.get('session') and yes(e.get('confirmed'))))
    others = sorted((v for v in vols if not v['area']), key=lambda v: v['name'])
    b = book(cfg, areas, tabs, overview, reviewers, counts, others, lambda a: names.get(a, ''))
    fresh = row is None
    title = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    sid = gsheets.create_sheet(drive, f'{title}: chair recruiting', (cfg.get('sheets') or {}).get('folder_id')) if fresh else row['sheet_id']
    b.write(sheets, sid, fresh)
    commit = __import__('subprocess').run(['git', '-C', data_dir, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    now = __import__('datetime').datetime.now().isoformat(timespec='minutes')
    if fresh:
        log.append({'kind': 'recruiting', 'area': '', 'round': '', 'commit': commit, 'content': '', 'sheet_id': sid, 'url': gsheets.url(sid), 'made': now})
    else:
        row.update(commit=commit, made=now)
    S.write_csv(log_path, LOG_COLS, log)
    save(data_dir, {k: e for k, e in entries.items() if any(e.get(f) for f in ('emailed', 'confirmed', 'availability', 'notes', 'session'))
                    or (e.get('abstract_id') and (k[1], k[2]) not in {(v['name'], v['email']) for v in vols})})
    S.write_csv(os.path.join(data_dir, 'chairs', 'area_status.csv'), ['area', 'responsible', 'status'],
                [{'area': a, 'responsible': overview.get(a, (reviewers.get(a, ''), ''))[0], 'status': overview.get(a, ('', ''))[1]} for a in areas])
    S.write_csv(os.path.join(data_dir, 'chairs', 'volunteers.csv'),
                ['volunteer_id', 'name', 'email', 'affiliation', 'chair_mode', 'presenting_mode', 'chaired_before', 'talk_ids',
                 'own_sessions', 'area', 'match_note'], vols)
    notes = [(k, e) for k, e in entries.items() if e.get('notes') and yes(e.get('confirmed'))]
    if notes:                                     # for Claude to read before placing: wishes the code cannot act on
        os.makedirs(os.path.join(data_dir, 'work', 'chairs'), exist_ok=True)
        with open(os.path.join(data_dir, 'work', 'chairs', 'notes.md'), 'w', encoding='utf-8') as f:
            f.write('# Notes on confirmed chairs (read before placing; type a Session to honour a wish)\n\n' +
                    '\n'.join(f"- {k[0]} | {k[1]} | session {e.get('session') or '(none yet)'} | {e['notes']}" for k, e in sorted(notes)) + '\n')
    print('recruiting sheet:', gsheets.url(sid))
    print(f"{len(vols)} volunteers; chairs needed {sum(c[0] for c in counts.values())}; "
          f"confirmed {sum(1 for e in entries.values() if yes(e.get('confirmed')))}; placed {sum(c[2] for c in counts.values())}; "
          f"{len(notes)} confirmed chairs with notes (work/chairs/notes.md)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['sync'])
    ap.add_argument('data_dir')
    a = ap.parse_args()
    sync(a.data_dir)


if __name__ == '__main__':
    main()
