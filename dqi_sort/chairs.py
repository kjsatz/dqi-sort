"""Stage 10: session chairs, recruited area by area: one spreadsheet with a tab per review area.

    python -m dqi_sort.chairs sync DATA_DIR

sync  reads the APS volunteer lists (config.yaml `chair_volunteers`: in_person and virtual files), keeps the rows whose
      sub-category starts with the division code, merges people by email, and links each to their abstracts (the
      row's abstract ID, plus any other talk by the same name, flagged to confirm). Then it writes or updates the chairs
      spreadsheet in the review folder:
      - Overview: one row per review area (the same areas as the review sheets), with Responsible (the subject-matter
        expert who recruits for the area; pre-filled with its reviewer) and Status, both editable, and the chairs needed
        and confirmed.
      - One tab per area: its chair slots (one per in-person session, two per virtual session; no backups), each with
        the session, title, time and room and four editable columns, Chair, Email, Status, Note; then the volunteers
        whose own talk is in that area, with when they present. A chair from the expert's own network is simply typed in.
      - Other volunteers (abstract not in our program) and How to fill in.
      What people typed is read back first and kept, and saved to chairs/chairs.csv and chairs/area_status.csv. A Check
      column flags a chair who presents at the session's time, chairs two sessions at once, or (in a virtual session)
      does not present virtually. Sessions fall in their current review area, so a session moved after review is simply
      listed where it now is. Also writes chairs/volunteers.csv.
"""
import argparse, collections, json, os, re, sys
from dqi_sort import sessions as S

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
SLOT_COLS = ['Session', 'Title', 'When', 'Room', 'Slot', 'Chair', 'Email', 'Status', 'Note', 'Check']
EDIT = [5, 6, 7, 8]                       # Chair, Email, Status, Note
VOL_COLS = ['Volunteer', 'Email', 'Affiliation', 'Can chair', 'Chaired before', 'Presents (their talks)', 'Match note', 'Status', 'Unavailable']
VOL_EDIT = [7, 8]                          # Status (confirmed, declined, no reply) and Unavailable (e.g. Mon AM; Thu)
NEW_ROWS = 8                               # blank volunteer rows for people from the expert's own network
HOW = [['Column', 'What to enter'],
       ['Chair', "The chair's name. Any suitable person: a volunteer listed below, or someone from your own network."],
       ['Email', "The chair's email."],
       ['Status', 'invited, confirmed or declined'],
       ['Note', 'Anything else, in free text'],
       ['', ''],
       ['Volunteers table', 'Instead of placing someone yourself, set a volunteer\'s Status to confirmed (and Unavailable, e.g. Mon AM; Thu). '
                            'On the next refresh Claude places each confirmed volunteer who is not yet in a slot on the open session in '
                            'this area closest to their own talk, where they are not a speaker and that does not clash with their talk '
                            'or their unavailability; the slot\'s Note says so. Add people from your network in the blank rows at the end '
                            '(name and email in the first two columns).'],
       ['', ''],
       ['Rules', 'One confirmed chair per in-person session and two per virtual session; no backups. A chair should not present '
                 'at the same time as the session (the Presents column shows when volunteers present), and virtual sessions are '
                 'best chaired by people presenting virtually. The Check column flags problems each time the sheet is refreshed. '
                 'Only the Chair, Email, Status and Note cells (and, on the Overview, Responsible and Status) can be edited.']]


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


def place(people, entries, vols, sess, sched, assign, talks, presents, data_dir):
    """Put each confirmed volunteer who is not yet in a slot on the open session in their area closest to their own
    talk, where they are not a speaker and that does not clash with their talks or unavailability. Edits entries."""
    import numpy as np
    from dqi_sort.pack import Space
    taken = {(e[1].lower() or norm(e[0])) for e in entries.values() if e[0]}
    by_key = {(v['name'], v['email']): v for v in vols}
    active = {i: t for i, t in talks.items() if t['status'] == 'active'}
    space = None
    notes = []
    for (area, name, email), (status, unav) in sorted(people.items()):
        if status != 'confirmed' or (email or norm(name)) in taken:
            continue
        v = by_key.get((name, email), {})
        own_talks = [i for i in (v.get('talk_ids') or '').split(';') if i in active]
        busy = presents.get(email, set()) | presents.get(norm(name), set())
        speaks = {assign.get(i) for i in own_talks}
        n_slots = 2 if area == 'VIRTUAL' else 1
        open_slots = [(x, str(k)) for x in sess if sess[x]['area'] == area and x in sched and x not in speaks
                      for k in range(1, n_slots + 1) if not entries.get((x, str(k)), ('',))[0]
                      and (sched[x]['day'], sched[x]['start']) not in busy and not unavailable(unav, sched[x]['day'], sched[x]['start'])]
        if not open_slots:
            notes.append(f'{name}: no open session in {area} without a clash'); continue
        if own_talks:
            space = space or Space(data_dir, active)
            x0 = np.mean([space.vec(i) for i in own_talks if space.vec(i) is not None], axis=0)
            members = collections.defaultdict(list)
            for i, a in assign.items():
                if a and i in active:
                    members[a].append(i)
            open_slots.sort(key=lambda xs: -float(space.centroid(members[xs[0]]) @ x0))
        x, k = open_slots[0]
        entries[(x, k)] = (name, email, 'confirmed', 'placed by Claude: the closest open session to their own talk, with no clash')
        taken.add(email or norm(name))
    for n in notes:
        print('PLACE', n)
    return notes


def read_back(sheets, sid):
    """What people typed: ({(session, slot): (chair, email, status, note)}, {area: (responsible, status)})."""
    entries, overview, people = {}, {}, {}
    try:
        meta = sheets.spreadsheets().get(spreadsheetId=sid, fields='sheets(properties(title))').execute(num_retries=5)
    except Exception:
        return entries, overview, people
    titles = [x['properties']['title'] for x in meta['sheets']]
    for t in titles:
        vals = sheets.spreadsheets().values().get(spreadsheetId=sid, range=f"'{t}'!A2:J2000").execute(num_retries=5).get('values', [])
        if not vals:
            continue
        head = vals[0]
        if t == 'Overview' and head[:1] == ['Area']:
            for r in vals[1:]:
                r = r + [''] * 8
                if r[0]:
                    overview[r[0]] = (r[2].strip(), r[6].strip())
        elif head[:1] == ['Session']:
            in_vols = False
            for r in vals[1:]:
                r = r + [''] * 10
                if r[0] == 'Volunteer':
                    in_vols = True; continue
                if not in_vols:
                    if r[0]:
                        entries[(r[0], r[4])] = tuple(x.strip() for x in r[5:9])
                elif r[0].strip():
                    people[(t, r[0].strip(), r[1].strip().lower())] = (r[7].strip().lower(), r[8].strip())
    return entries, overview, people


def sync(data_dir):
    from dqi_sort import gsheets
    cfg = S.load_config(data_dir)
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    assign = {a['talk_id']: a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))}
    slots = {s['slot_id']: s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
    sched = {r['session_id']: slots[r['slot_id']] for r in S.read_csv(os.path.join(data_dir, 'schedule', 'schedule.csv'))}
    rooms = {r['room_id']: r for r in S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    names = {a: v.get('name', '') for a, v in (cfg.get('areas') or {}).items()}
    spath = os.path.join(data_dir, 'sorting', 'area_status.csv')
    reviewers = {r['area']: r['responsible'] for r in S.read_csv(spath)} if os.path.exists(spath) else {}
    when = lambda x: f"{sched[x]['day']} {sched[x]['start']}–{sched[x]['end']}" if x in sched else ''
    vols = volunteers(data_dir, cfg, talks)
    for v in vols:
        own = [assign.get(i, '') for i in v['talk_ids'].split(';') if i]
        v['own_sessions'] = ';'.join(x for x in own if x)
        v['area'] = next((sess[x]['area'] for x in own if x in sess), '')
        v['presents'] = '; '.join(f"{x} ({when(x)})" for x in own if x in sched)
    log_path = os.path.join(data_dir, 'sorting', 'sheets.csv')
    log = S.read_csv(log_path) if os.path.exists(log_path) else []
    row = next((r for r in reversed(log) if r['kind'] == 'chairs-areas'), None)
    drive, sheets = gsheets.services()
    entries, overview, people = read_back(sheets, row['sheet_id']) if row else ({}, {}, {})
    # who presents when, to check chairs
    presents = collections.defaultdict(set)              # normalised name or email -> {(day, start)}
    for v in vols:
        for x in v['own_sessions'].split(';'):
            if x in sched:
                presents[v['email']].add((sched[x]['day'], sched[x]['start']))
                presents[norm(v['name'])].add((sched[x]['day'], sched[x]['start']))
    for i, t in talks.items():
        if t['status'] == 'active' and assign.get(i) in sched:
            presents[norm(t['speaker'])].add((sched[assign[i]]['day'], sched[assign[i]]['start']))
    virtual_people = {v['email'] for v in vols if 'virtual' in v['presenting_mode']} | {norm(v['name']) for v in vols if 'virtual' in v['presenting_mode']}
    placed_notes = place(people, entries, vols, sess, sched, assign, talks, presents, data_dir)
    chairing = collections.defaultdict(list)
    for (sid_, slot), (chair, email, status, note) in entries.items():
        if chair and sid_ in sched:
            chairing[email.lower() or norm(chair)].append((sched[sid_]['day'], sched[sid_]['start'], sid_))
    areas = sorted({s['area'] for s in sess.values()}, key=lambda a: (a == 'VIRTUAL', a))
    tabs, saved = {}, []
    for area in areas:
        rows = []
        for x in sorted((x for x in sess if sess[x]['area'] == area), key=lambda x: (DAYS.index(sched[x]['day']) if x in sched else 9, sched.get(x, {}).get('start', ''), x)):
            for k in range(1, (2 if area == 'VIRTUAL' else 1) + 1):
                chair, email, status, note = entries.get((x, str(k)), ('', '', '', ''))
                check = []
                key = email.lower() or norm(chair)
                if chair and x in sched:
                    t = (sched[x]['day'], sched[x]['start'])
                    if t in presents.get(email.lower(), set()) | presents.get(norm(chair), set()):
                        check.append('presents at this time')
                    if sum(1 for d, st, other in chairing[key] if (d, st) == t) > 1:
                        check.append('chairs another session at this time')
                    if area == 'VIRTUAL' and not ({email.lower(), norm(chair)} & virtual_people):
                        check.append('not a virtual presenter (fine if they agree)')
                room = rooms.get(sched.get(x, {}).get('room_id', ''), {}).get('name', 'virtual') if x in sched else ''
                rows.append([x, sess[x]['title'], when(x), room, k, chair, email, status, note, '; '.join(check)])
                saved.append({'session_id': x, 'slot': k, 'chair': chair, 'email': email, 'status': status, 'note': note, 'check': '; '.join(check)})
        tabs[area] = rows
    write_sheet(data_dir, cfg, drive, sheets, log, log_path, row, areas, names, tabs, vols, talks, overview, reviewers, people)
    os.makedirs(os.path.join(data_dir, 'chairs'), exist_ok=True)
    S.write_csv(os.path.join(data_dir, 'chairs', 'chairs.csv'), ['session_id', 'slot', 'chair', 'email', 'status', 'note', 'check'], saved)
    S.write_csv(os.path.join(data_dir, 'chairs', 'area_status.csv'), ['area', 'responsible', 'status'],
                [{'area': a, 'responsible': overview.get(a, (reviewers.get(a, ''), ''))[0], 'status': overview.get(a, ('', ''))[1]} for a in areas])
    S.write_csv(os.path.join(data_dir, 'chairs', 'volunteers.csv'),
                ['volunteer_id', 'name', 'email', 'affiliation', 'chair_mode', 'presenting_mode', 'chaired_before', 'talk_ids',
                 'own_sessions', 'area', 'match_note'], vols)
    need = sum(len(r) for r in tabs.values())
    done = sum(1 for x in saved if x['status'].lower() == 'confirmed')
    print(f'{len(vols)} volunteers; {need} chair slots in {len(areas)} areas; {done} confirmed; '
          f"{sum(1 for x in saved if x['check'])} flagged by the check")


def write_sheet(data_dir, cfg, drive, sheets, log, log_path, row, areas, names, tabs, vols, talks, overview, reviewers, people):
    from dqi_sort import gsheets
    from dqi_sort.sheets import Book, tab_requests, protect_req, color_req, HEADER_ROW, LOG_COLS, NOTES
    folder = (cfg.get('sheets') or {}).get('folder_id')
    title = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    b = Book(f'{title}: session chairs, by review area. Edit only the tinted cells.')
    orows = []
    for a in areas:
        n = len(tabs[a])
        resp, stat = overview.get(a, (reviewers.get(a, ''), ''))
        confirmed = f'=COUNTIF(\'{a}\'!H{HEADER_ROW + 1}:H{HEADER_ROW + n},"confirmed")'
        orows.append([a, names.get(a, ''), resp, len({r[0] for r in tabs[a]}), n, confirmed, stat])
    b.tab('Overview', ['Area', 'Name', 'Responsible', 'Sessions', 'Chairs needed', 'Confirmed', 'Status'], orows,
          lambda sid, n: tab_requests(sid, n, [80, 320, 200, 80, 100, 90, 320], wrap_cols=[1, 6], notes_cols=[2, 6]) + protect_req(sid, n, [2, 6]))
    for a in areas:
        mine = sorted((v for v in vols if v['area'] == a), key=lambda v: v['name'])
        known = {(v['name'], v['email']) for v in mine}
        vrows = [[v['name'], v['email'], v['affiliation'], v['chair_mode'].replace('_', '-'), v['chaired_before'], v['presents'], v['match_note'],
                  *people.get((a, v['name'], v['email']), ('', ''))] for v in mine]
        vrows += [[n, e, '', '', '', '', 'added by the area', *people[(t, n, e)]] for (t, n, e) in people if t == a and (n, e) not in known]
        vrows += [[''] * 9 for _ in range(NEW_ROWS)]
        n_slots = len(tabs[a])
        rows = tabs[a] + [[''] * 10, VOL_COLS + [''], *[r + [''] for r in vrows]]

        def fmt(sid, n, n_slots=n_slots):
            reqs = tab_requests(sid, n, [80, 300, 150, 110, 45, 170, 200, 90, 220, 220], wrap_cols=[1, 5, 8, 9])
            reqs += [color_req(sid, HEADER_ROW, HEADER_ROW + n_slots, c, c + 1, NOTES) for c in EDIT]
            reqs.append({'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': HEADER_ROW + n_slots + 1, 'endRowIndex': HEADER_ROW + n_slots + 2},
                                        'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}})
            reqs.append({'setDataValidation': {'range': {'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_slots,
                                                         'startColumnIndex': 7, 'endColumnIndex': 8},
                                               'rule': {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': v} for v in ('invited', 'confirmed', 'declined')]},
                                                        'showCustomUi': True, 'strict': False}}})
            v0, nv = HEADER_ROW + n_slots + 2, n - n_slots - 2      # the volunteer rows
            reqs += [color_req(sid, v0, v0 + nv, c, c + 1, NOTES) for c in VOL_EDIT]
            reqs += [color_req(sid, v0 + nv - NEW_ROWS, v0 + nv, 0, 2, NOTES)]
            free = [{'sheetId': sid, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_slots, 'startColumnIndex': c, 'endColumnIndex': c + 1} for c in EDIT]
            free += [{'sheetId': sid, 'startRowIndex': v0, 'endRowIndex': v0 + nv, 'startColumnIndex': c, 'endColumnIndex': c + 1} for c in VOL_EDIT]
            free += [{'sheetId': sid, 'startRowIndex': v0 + nv - NEW_ROWS, 'endRowIndex': v0 + nv, 'startColumnIndex': 0, 'endColumnIndex': 2}]
            return reqs + [{'addProtectedRange': {'protectedRange': {'range': {'sheetId': sid}, 'unprotectedRanges': free, 'warningOnly': False,
                                                                     'description': 'Generated by dqi_sort.chairs'}}}]
        b.tab(a, SLOT_COLS, rows, fmt)
    other = [[v['name'], v['email'], v['affiliation'], v['chair_mode'].replace('_', '-'), v['chaired_before'], v['match_note']]
             for v in sorted(vols, key=lambda v: v['name']) if not v['area']]
    b.tab('Other volunteers', ['Volunteer', 'Email', 'Affiliation', 'Can chair', 'Chaired before', 'Note'], other,
          lambda sid, n: tab_requests(sid, n, [180, 220, 220, 90, 90, 360], wrap_cols=[2, 5]) + protect_req(sid))
    b.tab('How to fill in', HOW[0], HOW[1:], lambda sid, n: tab_requests(sid, n, [140, 700], wrap_cols=[1]) + protect_req(sid))
    fresh = row is None
    sid = gsheets.create_sheet(drive, f'{title}: session chairs', folder) if fresh else row['sheet_id']
    b.write(sheets, sid, fresh)
    commit = __import__('subprocess').run(['git', '-C', data_dir, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    now = __import__('datetime').datetime.now().isoformat(timespec='minutes')
    if fresh:
        log.append({'kind': 'chairs-areas', 'area': '', 'round': '', 'commit': commit, 'content': '', 'sheet_id': sid, 'url': gsheets.url(sid), 'made': now})
    else:
        row.update(commit=commit, made=now)
    S.write_csv(log_path, LOG_COLS, log)
    print('chairs sheet:', gsheets.url(sid))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['sync'])
    ap.add_argument('data_dir')
    a = ap.parse_args()
    sync(a.data_dir)


if __name__ == '__main__':
    main()
