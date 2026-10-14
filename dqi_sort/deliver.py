"""Stage 11: the sheet for APS, a copy of their sorting page with our sort filled in.

    python -m dqi_sort.deliver DATA_DIR [--local] [--force]

Runs the validator with the delivery checks first and stops on any ERROR (--force writes anyway, marked as a draft
on every page, for a look before the chairs are in). Then writes one long page per track (In person, Virtual), in
the layout of APS's 2026 sorting page, with no split by area:
- top left, the sorting categories: code, title, and the abstracts of each (orals, invited, sessions' worth);
- columns J-M, the session slots per time block: allocated (our room slots), created (sessions placed), remaining;
- from column O, Created Sessions: session code, oral and invited counts, date and time, title, the chair (name,
  email, affiliation, status; two chairs for a virtual session) and the room;
- below the categories, every abstract in APS's own columns, as received, with Session Abbreviation, Speaking Order
  and Sorter Notes filled in: the sessions in area order (as in the review), each talk in speaking order; then the
  talks in no session (exchanged to another unit, poster, duplicate, withdrawn) with the reason as the sorter note.
  A talk added late or received from another unit, not in APS's list, gets a row built from talks.csv.
A third page, Reconciliation, lists every omission from and addition to APS's list with the logged decision behind
it (the same text is in views/reconciliation.md).

Writes delivery/in_person.csv and delivery/virtual.csv (the abstract lists as sent), delivery/sessions.csv (the
session tables), views/reconciliation.md, and the Google Sheet in the review folder: made once, then rewritten in
place, logged in sorting/sheets.csv as kind 'delivery'; and commits them to the data repo. --local skips the sheet.
"""
import argparse, collections, csv, datetime, json, os, subprocess, sys
from dqi_sort import sessions as S, validate as V

DAYNAME = {'Mon': 'Mon', 'Tue': 'Tues', 'Wed': 'Wed', 'Thu': 'Thurs', 'Fri': 'Fri', 'Sat': 'Sat', 'Sun': 'Sun'}
TRACKS = {'in_person': 'In person', 'virtual': 'Virtual'}
ALLOC_COL, SESS_COL = 9, 14                      # J and O, as on the 2026 page
FIELD_HEADER = {'session_id': 'Session Abbreviation', 'order': 'Speaking Order', 'sorter_note': 'Sorter Notes'}
WIDTHS = {'ID': 80, 'First Name': 110, 'Last Name': 120, 'Affiliation': 180, 'SC': 75, 'Type': 65, 'Title': 320, 'Body': 260,
          'Submitter Notes': 200, 'Session Abbreviation': 110, 'Speaking Order': 75, 'Sorter Notes': 220}


def ampm(hhmm):
    h, m = map(int, hhmm.split(':'))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def when(slot):
    return f"{DAYNAME.get(slot['day'], slot['day'])}, {ampm(slot['start'])} – {ampm(slot['end'])}"


def area_order(cfg, sess):
    known = list(cfg.get('areas') or {})
    return sorted(sess, key=lambda sid: (known.index(sess[sid]['area']) if sess[sid]['area'] in known else len(known), S.id_key(sid)))


def chair_info(data_dir, chairs):
    """{session: [(name, email, affiliation, status)]} from the confirmed chairs; affiliation from the volunteer list."""
    vols = V.read(data_dir, 'chairs', 'volunteers.csv')
    by_email = {v['email'].lower(): v['affiliation'] for v in vols if v.get('email')}
    by_name = {V.norm(v['name']): v['affiliation'] for v in vols}
    out = collections.defaultdict(list)
    for c in sorted(chairs, key=lambda c: c['name']):
        aff = c.get('affiliation') or by_email.get((c.get('email') or '').lower()) or by_name.get(V.norm(c['name']), '')
        for x in V.chair_codes(c):
            out[x].append((c['name'], c.get('email', ''), aff, 'Confirmed'))
    return out


def talk_row(header, cols, t, ab, cfg):
    """A row in APS's columns for a talk that is not in APS's list (a late addition, or received from another unit)."""
    first, _, last = t['speaker'].rpartition(' ')
    types = {v: k for k, v in (cfg.get('aps_types') or {}).items()}
    val = {'talk_id': t['talk_id'], 'first_name': first, 'last_name': last, 'speaker': t['speaker'], 'affiliation': t['affiliation'],
           'submitted_category': t['submitted_category'], 'type': types.get(t['type'], t['type']), 'title': t['title'],
           'body': ab.get('body', ''), 'submitter_notes': ab.get('submitter_notes', ''), 'time_windows': t.get('time_windows', '')}
    return [val.get(cols.get(h), '') for h in header]


def build(data_dir, d=None, summary=None):
    """{track: page}, page = dict(header, rows (abstract list), groups (session per row), sessions (table), grid)."""
    d = d or V.load(data_dir)
    if summary is None:
        summary, _ = V.reconcile(d)
    cfg, talks, sess, members, sched = d['cfg'], d['talks'], d['sess'], d['members'], d['sched']
    colmap = {k.strip(): v for k, v in (cfg.get('aps_columns') or {}).items()}
    abstracts = {}
    p = os.path.join(data_dir, 'abstracts.jsonl')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            abstracts = {r['talk_id']: r for r in map(json.loads, f) if r}
    chairs = chair_info(data_dir, d['chairs'])
    added = {i: V.why_added(e).split(' (')[0].capitalize() for i, e in summary['added']}
    gone = {i: V.short(s, e) for i, s, e in summary['omitted']}
    pages = {}
    for track in ('in_person', 'virtual'):
        if track in d['aps']:
            header, raw, k = d['aps'][track]
            keep = [c for c, h in enumerate(header) if h and not h.isdigit()]      # drop blank or stray numeric headers
            header, raw, k = [header[c] for c in keep], [[r[c] for c in keep] for r in raw], keep.index(k)
        else:
            header, raw, k = [h for h, f in colmap.items() if f not in ('time_windows',) or track == 'virtual'], [], 0
        cols = {h: colmap[h] for h in header if h in colmap}
        at = {f: header.index(h) for h, f in cols.items() if f in ('talk_id', 'submitted_category')}
        at.setdefault('talk_id', k)
        for f, default in FIELD_HEADER.items():
            h = next((h for h, x in cols.items() if x == f), default)
            if h not in header:
                header.append(h)
            cols[h] = f
            at[f] = header.index(h)
        raw_by = {r[k].strip(): r + [''] * (len(header) - len(r)) for r in raw}
        mine = [sid for sid in area_order(cfg, sess) if (sess[sid]['area'] == 'VIRTUAL') == (track == 'virtual')]
        rows, groups, table, done = [], [], [], set()

        def row_of(i):
            r = list(raw_by[i]) if i in raw_by else talk_row(header, cols, talks[i], abstracts.get(i, {}), cfg)
            return r + [''] * (len(header) - len(r))
        for sid in mine:
            m = members[sid]
            for n, i in enumerate(m, 1):
                r = row_of(i)
                r[at['session_id']], r[at['order']], r[at['sorter_note']] = sid, n, added.get(i, '')
                rows.append(r); groups.append(sid); done.add(i)
            per = 2 if track == 'virtual' else 1
            ch = chairs.get(sid, [])[:per] + [('', '', '', '')] * max(0, per - len(chairs.get(sid, [])))
            table.append([sid, sum(1 for i in m if talks[i]['type'] != 'invited'), sum(1 for i in m if talks[i]['type'] == 'invited'),
                          when(sched[sid]) if sid in sched else '', sess[sid]['title']] + [x for c in ch for x in c]
                         + [(d['rooms'].get(sched[sid].get('room_id') or '') or {}).get('name', '') if sid in sched else ''])
        rest = [i for i in raw_by if i not in done] + [i for i, t in talks.items() if t['track'] == track and i not in raw_by and i not in done]
        for i in sorted(dict.fromkeys(rest), key=S.id_key):
            r = row_of(i)
            st = talks.get(i, {}).get('status', '')
            r[at['session_id']], r[at['order']] = '', ''
            r[at['sorter_note']] = gone.get(i) or {'active': 'not yet in a session', 'exchange_pending': 'offered to another unit, pending'}.get(st, st)
            rows.append(r); groups.append(None)
        chair_head = (['Session Chair\nName', 'Session Chair\nEmail', 'Session Chair\nAffiliation', 'Session Chair Status'] if track == 'in_person' else
                      [f'Session Chair {n}\n{x}' for n in (1, 2) for x in ('Name', 'Email', 'Affiliation', 'Status')])
        sess_head = ['Session\nAbbreviation', '# Oral\nAbstracts', '# Invited\nAbstracts', 'Date/Time', 'Session Title (in title case)'] + chair_head + ['Room']
        pages[track] = dict(header=header, rows=rows, groups=groups, sess_head=sess_head, sessions=table,
                            grid=grid(track, cfg, header, rows, at, talks, sess_head, table, d))
    return pages


def grid(track, cfg, header, rows, at, talks, sess_head, table, d):
    """The page as a list of rows: categories, slot allocation and sessions at the top, the abstract list below."""
    sc, idc = at.get('submitted_category'), at['talk_id']
    count = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        t = talks.get(str(r[idc]).strip(), {})
        if sc is not None:
            count[r[sc]][1 if t.get('type') == 'invited' else 0] += 1
    units = (cfg.get('virtual_session_min') or 120) // S.UNIT_MIN if track == 'virtual' else max(cfg.get('session_lengths_min') or [144]) // S.UNIT_MIN
    cats = dict(cfg.get('dqi_categories') or {})
    cats.update({c: '' for c in count if c and c not in cats})
    cells = {}

    def put(r, c, v):
        cells[(r, c)] = v
    label = TRACKS[track]
    put(1, 0, f'{label}: categories')
    for c, h in enumerate(['Sorting Category', 'Title', '', '', '# Orals', '# Invited', '# Sessions']):
        put(2, c, h)
    r = 3
    for code in list(cfg.get('dqi_categories') or {}) + sorted(c for c in cats if c not in (cfg.get('dqi_categories') or {})):
        o, i = count.get(code, [0, 0])
        for c, v in enumerate([code, cats[code], '', '', o, i, round((o + 3 * i) / units, 2)]):
            put(r, c, v)
        r += 1
    tot = [sum(v[0] for v in count.values()), sum(v[1] for v in count.values())]
    for c, v in enumerate(['TOTAL:', '', '', '', tot[0], tot[1], round((tot[0] + 3 * tot[1]) / units, 2)]):
        put(r, c, v)
    cat_end = r
    tz = cfg.get('time_zone')
    put(0, ALLOC_COL, f'{label} Session Allocations')
    for c, h in enumerate([f"Date/Time{f' ({tz})' if tz else ''}", 'Sessions\nAllocated', '# Sessions\nCreated', '# Sessions\nRemaining']):
        put(1, ALLOC_COL + c, h)
    blocks = collections.OrderedDict()
    days = list(DAYNAME)
    for s in sorted((s for s in d['slots'].values() if s['track'] == track), key=lambda s: (days.index(s['day']) if s['day'] in days else 9, s['start'], s['end'])):
        blocks.setdefault(when(s), [0, 0])[0] += 1
    used = {r['slot_id'] for r in d['schedule']}
    for s in d['slots'].values():
        if s['track'] == track and s['slot_id'] in used:
            blocks[when(s)][1] += 1
    r = 2
    for k, (n, m) in blocks.items():
        for c, v in enumerate([k, n, m, n - m]):
            put(r, ALLOC_COL + c, v)
        r += 1
    if blocks:
        for c, v in enumerate(['Totals', sum(v[0] for v in blocks.values()), sum(v[1] for v in blocks.values()),
                               sum(v[0] - v[1] for v in blocks.values())]):
            put(r, ALLOC_COL + c, v)
    alloc_end = r
    s0 = max(SESS_COL, len(header) + 1)
    put(0, s0, 'Created Sessions')
    for c, h in enumerate(sess_head):
        put(1, s0 + c, h)
    for n, row in enumerate(table):
        for c, v in enumerate(row):
            put(2 + n, s0 + c, v)
    head = max(cat_end, alloc_end) + 3
    for c, h in enumerate(header):
        put(head, c, h)
    for n, row in enumerate(rows):
        for c, v in enumerate(row):
            put(head + 1 + n, c, v)
    n_rows = max(rr for rr, _ in cells) + 1
    n_cols = max(cc for _, cc in cells) + 1
    out = [[''] * n_cols for _ in range(n_rows)]
    for (rr, cc), v in cells.items():
        out[rr][cc] = v
    return dict(values=out, head=head, s0=s0, n_sess=len(table), cat_end=cat_end, alloc_end=alloc_end)


def recon_rows(summary, talks):
    track = lambda i: TRACKS.get(talks.get(i, {}).get('track'), '')
    return ([['Talk ID', 'Track', 'Change', 'Why']]
            + [[i, track(i), 'omitted', V.why(s, e)] for i, s, e in summary['omitted']]
            + [[i, track(i), 'added', V.why_added(e)] for i, e in summary['added']])


# ---------- writing ----------
def write_local(data_dir, pages, summary, stamp_text):
    out = os.path.join(data_dir, 'delivery')
    os.makedirs(out, exist_ok=True)
    for track, pg in pages.items():
        with open(os.path.join(out, f'{track}.csv'), 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, lineterminator='\n')
            w.writerow(pg['header']); w.writerows(pg['rows'])
    with open(os.path.join(out, 'sessions.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['track'] + [h.replace('\n', ' ') for h in pages['virtual']['sess_head']])
        for track, pg in pages.items():
            for row in pg['sessions']:
                if track == 'in_person':
                    row = row[:9] + [''] * 4 + row[9:]
                w.writerow([track] + row)
    os.makedirs(os.path.join(data_dir, 'views'), exist_ok=True)
    with open(os.path.join(data_dir, 'views', 'reconciliation.md'), 'w', encoding='utf-8') as f:
        f.write(f'# Reconciliation: the APS input against the delivered list\n\n{stamp_text}\n\n{V.reconciliation_text(summary)}\n')


def page_format(sid, pg):
    from dqi_sort.sheets import color_req, BAND
    g = pg['grid']
    bold = lambda r0, r1, c0, c1: {'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': r0, 'endRowIndex': r1, 'startColumnIndex': c0, 'endColumnIndex': c1},
                                                  'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'wrapStrategy': 'WRAP', 'verticalAlignment': 'BOTTOM'}},
                                                  'fields': 'userEnteredFormat(textFormat,wrapStrategy,verticalAlignment)'}}
    reqs = [{'repeatCell': {'range': {'sheetId': sid}, 'cell': {'userEnteredFormat': {'wrapStrategy': 'CLIP', 'verticalAlignment': 'TOP'}},
                            'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment)'}},
            bold(0, 1, 0, len(g['values'][0])), bold(2, 3, 0, 7), bold(g['cat_end'], g['cat_end'] + 1, 0, 7),
            bold(1, 2, ALLOC_COL, ALLOC_COL + 4), bold(1, 2, g['s0'], g['s0'] + len(pg['sess_head'])),
            bold(g['head'], g['head'] + 1, 0, len(pg['header']))]
    for c, h in enumerate(pg['header']):
        reqs.append({'updateDimensionProperties': {'range': {'sheetId': sid, 'dimension': 'COLUMNS', 'startIndex': c, 'endIndex': c + 1},
                                                   'properties': {'pixelSize': WIDTHS.get(h, 110)}, 'fields': 'pixelSize'}})
    for c, w in enumerate([100, 80, 80, 170, 300] + [150, 200, 180, 90] * (2 if len(pg['sess_head']) > 10 else 1) + [130]):
        reqs.append({'updateDimensionProperties': {'range': {'sheetId': sid, 'dimension': 'COLUMNS', 'startIndex': g['s0'] + c, 'endIndex': g['s0'] + c + 1},
                                                   'properties': {'pixelSize': w}, 'fields': 'pixelSize'}})
    k, start = 0, 0
    groups = pg['groups'] + ['<end>']
    for n in range(1, len(groups)):
        if groups[n] != groups[start]:
            if groups[start] is not None and k % 2 == 0:
                reqs.append(color_req(sid, g['head'] + 1 + start, g['head'] + 1 + n, 0, len(pg['header']), BAND))
            k += groups[start] is not None
            start = n
    return reqs


def write_sheet(data_dir, cfg, pages, summary, title_line, talks):
    from dqi_sort import gsheets
    from dqi_sort.sheets import LOG_COLS, git
    drive, sheets = gsheets.services()
    log_path = os.path.join(data_dir, 'sorting', 'sheets.csv')
    log = S.read_csv(log_path) if os.path.exists(log_path) else []
    row = next((r for r in reversed(log) if r['kind'] == 'delivery'), None)
    title = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    sid = row['sheet_id'] if row else gsheets.create_sheet(drive, f'{title}: sorted for APS', (cfg.get('sheets') or {}).get('folder_id'))
    tabs = [(TRACKS[t], pages[t]['grid']['values'], pages[t]) for t in ('in_person', 'virtual')]
    tabs.append(('Reconciliation', [[title_line], [V.reconciliation_text(summary).split('\n')[0]], []] + recon_rows(summary, talks), None))
    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields='sheets(properties(sheetId,title))').execute(num_retries=5)
    have = {s['properties']['title']: s['properties']['sheetId'] for s in meta['sheets']}
    reqs, ids = [], {}
    for k, (name, values, _) in enumerate(tabs):
        n_rows, n_cols = len(values) + 10, max(len(r) for r in values) + 2
        if name in have:
            ids[name] = have[name]
            reqs.append({'updateCells': {'range': {'sheetId': have[name]}, 'fields': '*'}})
        elif not row and k == 0:
            ids[name] = meta['sheets'][0]['properties']['sheetId']
            reqs.append({'updateSheetProperties': {'properties': {'sheetId': ids[name], 'title': name}, 'fields': 'title'}})
        else:
            ids[name] = 2000 + k
            reqs.append({'addSheet': {'properties': {'sheetId': ids[name], 'title': name, 'index': k}}})
        reqs.append({'updateSheetProperties': {'properties': {'sheetId': ids[name], 'gridProperties': {'rowCount': n_rows, 'columnCount': n_cols}},
                                               'fields': 'gridProperties(rowCount,columnCount)'}})
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={'requests': reqs}).execute(num_retries=5)
    data = []
    for name, values, pg in tabs:
        values = [list(r) for r in values]
        if pg:
            values[0][0] = title_line
        data.append({'range': f"'{name}'!A1", 'values': values})
    sheets.spreadsheets().values().batchUpdate(spreadsheetId=sid, body={'valueInputOption': 'RAW', 'data': data}).execute(num_retries=5)
    fmt = [r for name, _, pg in tabs if pg for r in page_format(ids[name], pg)]
    from dqi_sort.sheets import tab_requests
    fmt += tab_requests(ids['Reconciliation'], len(tabs[-1][1]), [90, 80, 90, 700])
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={'requests': fmt}).execute(num_retries=5)
    now = datetime.datetime.now().isoformat(timespec='minutes')
    commit = git(data_dir, 'rev-parse', '--short=7', 'HEAD')
    if row:
        row.update(commit=commit, made=now)
    else:
        log.append({'kind': 'delivery', 'area': '', 'round': '', 'commit': commit, 'content': '', 'sheet_id': sid, 'url': gsheets.url(sid), 'made': now})
    S.write_csv(log_path, LOG_COLS, log)
    return gsheets.url(sid)


def deliver(data_dir, local=False, force=False):
    from dqi_sort.sheets import stamp
    probs, summary = V.validate(data_dir, delivery=True, quiet=True)
    errs = [t for l, t in probs if l == 'ERROR']
    for t in errs[:40]:
        print('ERROR', t)
    if len(errs) > 40:
        print(f'... and {len(errs) - 40} more (python -m dqi_sort.validate {data_dir} --delivery)')
    if errs and not force:
        sys.exit(f'{len(errs)} validator errors: nothing written (--force writes a draft anyway)')
    commit, stamp_text = stamp(data_dir)
    cfg = S.load_config(data_dir)
    title = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    title_line = f'{title}: sorted for APS. {stamp_text}' + (f'. DRAFT: {len(errs)} validator errors' if errs else '')
    pages = build(data_dir, summary=summary)
    write_local(data_dir, pages, summary, title_line)
    print(V.reconciliation_text(summary))
    print(f"wrote delivery/ ({', '.join(f'{t}: {len(p['rows'])} abstracts, {len(p['sessions'])} sessions' for t, p in pages.items())}) and views/reconciliation.md")
    if not local:
        talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
        print('APS sheet:', write_sheet(data_dir, cfg, pages, summary, title_line, talks))
    paths = [p for p in ('delivery', 'views/reconciliation.md', 'sorting/sheets.csv') if os.path.exists(os.path.join(data_dir, p))]
    if not subprocess.run(['git', '-C', data_dir, 'rev-parse'], capture_output=True).returncode:
        subprocess.run(['git', '-C', data_dir, 'add', '--', *paths], check=True)
        r = subprocess.run(['git', '-C', data_dir, 'commit', '-q', '-m', f'deliver: the APS sheet from {commit}' + (' (draft)' if errs else ''), '--', *paths],
                           capture_output=True, text=True)
        print('committed to the data repo' if r.returncode == 0 else 'nothing new to commit')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--local', action='store_true', help='write the files only, not the Google Sheet')
    ap.add_argument('--force', action='store_true', help='write even with validator errors (marked as a draft)')
    a = ap.parse_args()
    deliver(a.data_dir, a.local, a.force)


if __name__ == '__main__':
    main()
