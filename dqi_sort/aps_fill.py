"""Stage 11 (2027 layout): fill APS's own sorting sheet with our in-person sessions, then read it back and check.

    python -m dqi_sort.aps_fill write DATA_DIR [SHEET_ID] [--dry-run] [--force]
    python -m dqi_sort.aps_fill check DATA_DIR [SHEET_ID]
    python -m dqi_sort.aps_fill schedule DATA_DIR      (views/schedule_for_aps.csv: the schedule for APS's grid)

SHEET_ID defaults to config aps_sheet.id, and the tab to aps_sheet.tabs.in_person (dqi_sort.aps_input).

APS's 2027 sheet keeps every in-person talk on one tab ("In-Person Sorting"): a table of sessions at the top (one
row per session: Length, Abbreviation, Session Title, Chair Name/Email/Affiliation, optional co-chair; the other
columns are APS's formulas) and below it the talk list in APS's order (ID ... Session, Order, Sorter Notes). Columns
and rows are found by their header names, not by position.

write   runs the validator's delivery checks for the in-person track and stops on an error (--force writes anyway).
        Saves the tab's current cells to work/aps_fill/ in the data folder (formulas as typed, to undo by hand), then
        writes, in one batch: each in-person session in area order (Length, Abbreviation = our session code, Title,
        the confirmed chair), clears the session rows left over, and sets every talk's Session and Order (1, 2, ...
        in speaking order; blank for a talk in no session). Sorter Notes are APS's and are left as they are. No other
        tab is touched: the Virtual tab, done separately, never is. Refuses a session row that holds an abbreviation
        that is not one of ours (someone else's entry) unless --force. --dry-run prints what it would write.
check   reads the tab back (values as shown) and compares it with the sort in git: the same sessions with the same
        length, title and chair; every talk in our sessions in its session at its position; no talk in a session we
        do not have; and APS's own formulas: the session type (mini-symposium when it has an invited talk), the talk
        count, and no session over capacity (Seats Left below 0). Writes views/aps_sheet_check.md. Exit 1 on a
        mismatch.
schedule  writes views/schedule_for_aps.csv, one row per in-person session sorted by day, time and room: code, title,
        type, length, day, date, start and end, APS block, room, APS room number, seats, recorded, chair. Send it with
        the `schedule_page --no-numbers` page; in 2027 APS entered it into its Summit Grid from this file.
"""
import argparse, collections, csv, datetime, json, os, re, sys
from dqi_sort import deliver as D, validate as V

TAB = 'In-Person Sorting'     # set from config aps_sheet.tabs.in_person by target()
LAST_COL = 'Z'
S_FIELDS = {'length': 'Length', 'abbr': 'Abbreviation', 'title': 'Session Title', 'chair': 'Chair Name',
            'email': 'Chair Email', 'aff': 'Chair Affiliation', 'co_chair': 'Co-Chair Name', 'co_email': 'Co-Chair Email',
            'co_aff': 'Co-Chair Affiliation', 'type': 'Session Type', 'n': '# Talks', 'left': 'Seats Left'}
T_FIELDS = {'id': 'ID', 'type': 'Type', 'session': 'Session', 'order': 'Order', 'note': 'Sorter Notes'}
WRITE_S = ['length', 'abbr', 'title', 'chair', 'email', 'aff', 'co_chair', 'co_email', 'co_aff']


def col_letter(c):
    s = ''
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def cell(row, c):
    return str(row[c]).strip() if c is not None and c < len(row) and row[c] is not None else ''


def find_cols(header, fields):
    """{field: column} by header name: an exact match, else the first header that starts with the name."""
    h = [str(x).strip() for x in header]
    out = {}
    for f, name in fields.items():
        exact = [c for c, x in enumerate(h) if x == name]
        loose = [c for c, x in enumerate(h) if x.startswith(name)]
        out[f] = (exact or loose or [None])[0]
    return out


def layout(values):
    """Where things are on the tab, from its cells as typed (formulas, not their values; a list of rows, 0-based):
    a session row is one between the two headers with APS's formula in column A."""
    sh = next((i for i, r in enumerate(values) if 'Abbreviation' in [str(x).strip() for x in r]
               and any(str(x).strip() == 'Session Title' for x in r)), None)
    th = next((i for i, r in enumerate(values) if r and str(r[0]).strip() == 'ID' and 'Session' in [str(x).strip() for x in r]), None)
    if sh is None or th is None or th < sh:
        raise SystemExit(f"{TAB}: could not find the session table header (Abbreviation, Session Title) above the talk header (ID ... Session)")
    scol, tcol = find_cols(values[sh], S_FIELDS), find_cols(values[th], T_FIELDS)
    missing = [S_FIELDS[f] for f in WRITE_S if scol[f] is None] + [T_FIELDS[f] for f in ('id', 'session', 'order') if tcol[f] is None]
    if missing:
        raise SystemExit(f"{TAB}: columns not found: {', '.join(missing)}")
    srows = [i for i in range(sh + 1, th) if i < len(values) and cell(values[i], 0).startswith('=')]  # APS's formula in A
    if not srows or srows != list(range(srows[0], srows[-1] + 1)):
        raise SystemExit(f'{TAB}: session rows are not one block ({len(srows)} rows)')
    trows = {}
    for i in range(th + 1, len(values)):
        t = cell(values[i], tcol['id'])
        if t.isdigit():
            trows[t] = i
    return dict(sh=sh, th=th, scol=scol, tcol=tcol, srows=srows, trows=trows)


def ours(data_dir, d=None):
    """Our in-person sessions in area order, [dict(sid, minutes, title, kind, chair, email, aff, talks)], and
    {talk: (session, position)}."""
    d = d or V.load(data_dir)
    sess, members = d['sess'], d['members']
    chairs = D.chair_info(data_dir, d['chairs'])
    out, place = [], {}
    for sid in D.area_order(d['cfg'], sess):
        if V.is_virtual(sess[sid]):
            continue
        ch = (chairs.get(sid) or [('', '', '', '')])[0]
        out.append(dict(sid=sid, minutes=int(sess[sid]['minutes']), title=sess[sid]['title'], kind=sess[sid].get('kind', ''),
                        chair=ch[0], email=ch[1], aff=ch[2], talks=list(members[sid]),
                        invited=sum(1 for t in members[sid] if d['talks'][t]['type'] == 'invited')))
        for n, t in enumerate(members[sid], 1):
            place[t] = (sid, n)
    return out, place


def plan(values, sessions, place, force=False):
    """(updates, problems): updates = [(A1 range, rows)] for one batch; problems stop the write unless forced."""
    L = layout(values)
    sc, tc, srows = L['scol'], L['tcol'], L['srows']
    problems = []
    mine = {s['sid'] for s in sessions}
    foreign = sorted({cell(values[i], sc['abbr']) for i in srows} - mine - {''})
    if foreign:
        problems.append(f"session rows hold abbreviations that are not ours: {', '.join(foreign)}")
    if len(sessions) > len(srows):
        problems.append(f'{len(sessions)} sessions but only {len(srows)} session rows')
    missing = sorted(t for t in place if t not in L['trows'])
    if missing:
        problems.append(f"talks in our sessions but not in APS's talk list: {', '.join(missing)}")
    if problems and not force:
        return [], problems
    updates = []
    for f in WRITE_S:                                   # one column at a time: the columns need not be adjacent
        c = sc[f]
        col = []
        for k, i in enumerate(srows):
            s = sessions[k] if k < len(sessions) else None
            v = '' if s is None else {'length': s['minutes'], 'abbr': s['sid'], 'title': s['title'], 'chair': s['chair'],
                                      'email': s['email'], 'aff': s['aff']}.get(f, '')
            col.append([v])
        updates.append((f"'{TAB}'!{col_letter(c)}{srows[0] + 1}:{col_letter(c)}{srows[-1] + 1}", col))
    first, last = min(L['trows'].values()), max(L['trows'].values())
    by_row = {i: t for t, i in L['trows'].items()}
    for f in ('session', 'order'):
        c = tc[f]
        col = []
        for i in range(first, last + 1):
            t = by_row.get(i)
            if t is None:
                col.append([cell(values[i], c)])       # not a talk row: keep what is there
            else:
                p = place.get(t)
                col.append([(p[0] if f == 'session' else p[1]) if p else ''])
        updates.append((f"'{TAB}'!{col_letter(c)}{first + 1}:{col_letter(c)}{last + 1}", col))
    return updates, problems


def compare(values, sessions, place, L):
    """Problems found reading the tab back (values as shown, laid out by layout() of the formulas) against our sort;
    [] when it matches."""
    sc, tc = L['scol'], L['tcol']
    out = []
    theirs = {}
    for i in L['srows']:
        r = values[i]
        a = cell(r, sc['abbr'])
        if a:
            if a in theirs:
                out.append(f'session {a}: on two rows')
            theirs[a] = r
    want = {s['sid']: s for s in sessions}
    out += [f'session {a}: on the sheet but not ours' for a in sorted(set(theirs) - set(want))]
    out += [f'session {a}: ours but not on the sheet' for a in sorted(set(want) - set(theirs))]
    for a in sorted(set(want) & set(theirs)):
        s, r = want[a], theirs[a]
        for f, v in (('length', str(s['minutes'])), ('title', s['title']), ('chair', s['chair']), ('email', s['email']), ('aff', s['aff'])):
            got = cell(r, sc[f])
            if got != v:
                out.append(f'session {a}: {S_FIELDS[f]} is "{got}", ours "{v}"')
        for f in ('co_chair', 'co_email', 'co_aff'):
            if cell(r, sc[f]):
                out.append(f'session {a}: {S_FIELDS[f]} is "{cell(r, sc[f])}", ours blank')
        if sc['n'] is not None and cell(r, sc['n']) != str(len(s['talks'])):
            out.append(f"session {a}: APS counts {cell(r, sc['n'])} talks, ours {len(s['talks'])}")
        if sc['left'] is not None:
            left = cell(r, sc['left'])
            try:
                if float(left) < 0:
                    out.append(f'session {a}: Seats Left {left} (over capacity)')
            except ValueError:
                out.append(f'session {a}: Seats Left is "{left}"')
        if sc['type'] is not None:
            mini = cell(r, sc['type']).lower().startswith('mini')
            if mini != (s['invited'] > 0):
                out.append(f"session {a}: APS's Session Type is \"{cell(r, sc['type'])}\" with {s['invited']} invited talks")
    for t, i in sorted(L['trows'].items()):
        got = (cell(values[i], tc['session']), cell(values[i], tc['order']))
        p = place.get(t)
        exp = (p[0], str(p[1])) if p else ('', '')
        if got != exp:
            out.append(f'talk {t}: Session/Order is {got[0] or "(blank)"}/{got[1] or "(blank)"}, ours {exp[0] or "(none)"}/{exp[1] or "-"}')
    out += [f"talk {t}: in our session {place[t][0]} but not in APS's talk list" for t in sorted(set(place) - set(L['trows']))]
    return out


def in_person_errors(d, probs):
    """The validator's errors that concern the in-person track: not about a virtual session or a virtual talk."""
    virtual = {s for s, x in d['sess'].items() if V.is_virtual(x)}
    vtalks = {t for t, x in d['talks'].items() if x['track'] == 'virtual'}
    if 'virtual' in d['aps']:
        header, rows, k = d['aps']['virtual']
        vtalks |= {r[k].strip() for r in rows}
    return [m for lvl, m in probs if lvl == 'ERROR' and m.split(':')[0].strip() not in virtual | vtalks]


def target(data_dir, sheet_id=None):
    """The sheet ID (argument, else config aps_sheet.id); sets TAB from config aps_sheet.tabs.in_person."""
    global TAB
    from dqi_sort import sessions as S
    a = S.load_config(data_dir).get('aps_sheet') or {}
    tab = (a.get('tabs') or {}).get('in_person')
    if tab and not tab.endswith('*'):
        TAB = tab
    sid = sheet_id or a.get('id')
    if not sid:
        raise SystemExit('no SHEET_ID: pass it, or set aps_sheet.id in config.yaml')
    return sid


def read_tab(sheets, sheet_id, render):
    return sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{TAB}'!A1:{LAST_COL}", valueRenderOption=render
                                              ).execute(num_retries=5).get('values', [])


def write(data_dir, sheet_id=None, dry_run=False, force=False):
    sheet_id = target(data_dir, sheet_id)
    d = V.load(data_dir)
    errs = in_person_errors(d, V.validate(data_dir, delivery=True, quiet=True)[0])
    if errs and not force:
        raise SystemExit('Validator errors for the in-person track (fix, or --force):\n  ' + '\n  '.join(errs))
    sessions, place = ours(data_dir, d)
    from dqi_sort import gsheets
    _, sheets = gsheets.services()
    values = read_tab(sheets, sheet_id, 'FORMULA')
    updates, problems = plan(values, sessions, place, force)
    if problems and not force:
        raise SystemExit('Not written:\n  ' + '\n  '.join(problems))
    for p in problems:
        print('WARNING (forced):', p)
    n_cells = sum(len(rows) for _, rows in updates)
    if dry_run:
        for rng, rows in updates:
            print(rng, f'{len(rows)} cells, first: {rows[:3]}')
        print(f'dry run: {len(sessions)} sessions, {len(place)} talks placed, {n_cells} cells')
        return
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(os.path.join(data_dir, 'work', 'aps_fill'), exist_ok=True)
    backup = os.path.join(data_dir, 'work', 'aps_fill', f'before_{stamp}.json')
    with open(backup, 'w', encoding='utf-8') as f:
        json.dump({'sheet_id': sheet_id, 'tab': TAB, 'values': values}, f)
    body = {'valueInputOption': 'RAW', 'data': [{'range': r, 'values': rows} for r, rows in updates]}
    sheets.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body=body).execute(num_retries=5)
    print(f"wrote {len(sessions)} sessions and {len(place)} talks' Session/Order to '{TAB}' ({n_cells} cells); "
          f'the tab as it was: {os.path.relpath(backup, data_dir)}')


def check(data_dir, sheet_id=None):
    sheet_id = target(data_dir, sheet_id)
    sessions, place = ours(data_dir)
    from dqi_sort import gsheets
    _, sheets = gsheets.services()
    L = layout(read_tab(sheets, sheet_id, 'FORMULA'))
    values = read_tab(sheets, sheet_id, 'FORMATTED_VALUE')
    probs = compare(values, sessions, place, L)
    lines = [f"# APS's sheet read back ({datetime.datetime.now():%b %d %H:%M})", '',
             f"Tab '{TAB}': {sum(1 for i in L['srows'] if cell(values[i], L['scol']['abbr']))} sessions on the sheet, "
             f"{len(L['trows'])} talks; ours: {len(sessions)} in-person sessions, {len(place)} talks in them.", '']
    lines += ([f'{len(probs)} mismatches:', ''] + [f'- {p}' for p in probs]) if probs else \
        ['Matches the sort in git: every session (length, title, chair), every talk (session, order), APS\'s session '
         'types and talk counts, and no session over capacity.']
    os.makedirs(os.path.join(data_dir, 'views'), exist_ok=True)
    with open(os.path.join(data_dir, 'views', 'aps_sheet_check.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 1 if probs else 0


DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAY_NAMES = dict(zip(DAYS, ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']))


def meeting_days(dates):
    """{'Mon': '2027-04-12', ...} from config meeting_dates like "April 12-16, 2027"; {} if it does not parse."""
    m = re.match(r'\s*([A-Za-z]+)\s+(\d+)\s*[-–]\s*(\d+),\s*(\d{4})', str(dates or ''))
    if not m:
        return {}
    try:
        first = datetime.datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(4)}', '%B %d %Y').date()
    except ValueError:
        return {}
    days = int(m.group(3)) - int(m.group(2)) + 1
    return {DAYS[(first + datetime.timedelta(k)).weekday()]: (first + datetime.timedelta(k)).isoformat() for k in range(days)}


def schedule_csv(data_dir):
    d = V.load(data_dir)
    sess, sched, rooms = d['sess'], d['sched'], d['rooms']
    chairs = D.chair_info(data_dir, d['chairs'])
    dates = meeting_days(d['cfg'].get('meeting_dates'))
    tz = d['cfg'].get('time_zone') or 'local'
    rows = []
    for sid, sl in sched.items():
        s = sess.get(sid)
        if not s or V.is_virtual(s) or not sl.get('room_id'):
            continue
        rm = rooms.get(sl['room_id'], {})
        rows.append({'Session Abbreviation': sid, 'Session Title': s['title'],
                     'Session Type': 'Mini-symposium' if s.get('kind') == 'mini-symposium' else 'Oral contributed',
                     'Length (min)': s['minutes'], 'Day': DAY_NAMES.get(sl['day'], sl['day']), 'Date': dates.get(sl['day'], ''),
                     f'Start ({tz})': sl['start'], f'End ({tz})': sl['end'], 'APS Block': sl.get('block', ''), 'Room': rm.get('name', sl['room_id']),
                     'APS Room #': rm.get('aps_room', ''), 'Seats': rm.get('capacity', ''), 'Recorded': rm.get('recorded', ''),
                     'Chair': ', '.join(c[0] for c in chairs.get(sid, []))})
    rows.sort(key=lambda r: (DAYS.index(next(k for k, v in DAY_NAMES.items() if v == r['Day'])) if r['Day'] in DAY_NAMES.values() else 9,
                             r[f'Start ({tz})'], r['Room']))
    out = os.path.join(data_dir, 'views', 'schedule_for_aps.csv')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]) if rows else ['Session Abbreviation'], lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} in-person sessions -> {os.path.relpath(out, data_dir)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['write', 'check', 'schedule'])
    ap.add_argument('data_dir')
    ap.add_argument('sheet_id', nargs='?')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'schedule':
        schedule_csv(a.data_dir)
    elif a.cmd == 'write':
        write(a.data_dir, a.sheet_id, a.dry_run, a.force)
    else:
        sys.exit(check(a.data_dir, a.sheet_id))


if __name__ == '__main__':
    main()
