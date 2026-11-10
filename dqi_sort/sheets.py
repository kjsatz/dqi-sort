"""Review sheets (sync-sheets): write the sort in git to Google Sheets.

    python -m dqi_sort.sheets sync DATA_DIR [--areas SCDEV,QEC | --all] [--reissue] [--no-attendance]

Run after every merge to the data repo, from the lead's computer (sign-in: docs/google_sheets.md). It
- makes a fresh area sheet for each area whose part of the sort changed since that area's last sheet (or the
  areas named). Area sheets are never rewritten: each round is a new file, named with the area, round and commit.
  An area whose current round is out (it has a Status and is not yet read back with `dqi_sort.review apply`) gets no
  new round: the reviewer keeps the sheet they started, and changes from elsewhere wait for the next round.
  With --reissue, an area whose current round nobody has started (no Status, not read back) is rewritten in place
  instead: same file, link and access, same round number, stamped with the new commit. For a change that lands before
  reviewers begin, so nobody has to switch links (and nobody without a Google account gets another invitation).
- then updates the shared sheet in place. Its first tab, Area assignments, links each area's current sheet and has
  two columns people fill in, Responsible and Status; sync reads them first and keeps them (Status is cleared when
  the area gets a new round), and saves them to
  sorting/area_status.csv. Its other tabs (session summary, sessions, lonely abstracts, moves) and the rest of the
  first tab are locked to the owner (the lead).

Access: a new round's area sheet gets the access of the area's previous sheet (people keep what they had; Drive
sends them no email), and every new sheet is open to anyone with the link at `sheets.link_sharing` in config.yaml
(reader, commenter or writer; unset: private). The shared sheet is updated in place, so its access stays as set.

Every sheet is stamped with the data repo's commit, so the sorting files must be committed first. The sheets made
are recorded in sorting/sheets.csv (kind, area, round, commit, content hash, sheet ID, link, time); the
assignments in sorting/area_status.csv (area, responsible, status), so git keeps a dated record of each.
Attendance estimates and suggested room sizes come from the attendance model (needs Ollama running).
"""
import argparse, collections, datetime, glob, hashlib, html, json, os, re, subprocess, sys
from dqi_sort import gsheets, pack, sessions as S

HEADER_ROW = 2                         # row 1: title and stamp; row 2: column names; data from row 3
BAND = {'red': 0.94, 'green': 0.96, 'blue': 0.99}
NOTES = {'red': 1.0, 'green': 0.97, 'blue': 0.88}
SHORT = {'red': 0.98, 'green': 0.85, 'blue': 0.85}
SIZES = ['small', 'medium', 'large']
COMMENTS_LABEL = 'Freeform comments for Claude →'
COMMENTS_COL = 6                       # the comment box: G1:I1 of an area sheet's Session summary, its label in F1
HIGHLIGHT = {'red': 1.0, 'green': 0.89, 'blue': 0.6}
LOG_COLS = ['kind', 'area', 'round', 'commit', 'content', 'sheet_id', 'url', 'made']


def git(data_dir, *args):
    return subprocess.run(['git', '-C', data_dir, *args], capture_output=True, text=True, check=True).stdout.strip()


def stamp(data_dir):
    dirty = git(data_dir, 'status', '--porcelain', '--', 'talks.csv', 'cards.jsonl', 'sorting', 'config.yaml')
    if dirty:
        sys.exit('commit the data repo first (the sheets are stamped with its commit):\n' + dirty)
    commit = git(data_dir, 'rev-parse', '--short=7', 'HEAD')
    now = datetime.datetime.now()
    return commit, f"Generated from git {commit}, {now.day} {now:%b %H:%M}"


# ---------- data ----------
def load(data_dir):
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    apath = os.path.join(data_dir, 'abstracts.jsonl')
    if os.path.exists(apath):                 # each talk's abstract as submitted, for reviewers to refer to
        with open(apath, encoding='utf-8') as f:
            for a in map(json.loads, filter(str.strip, f)):
                if a['talk_id'] in talks:
                    talks[a['talk_id']]['abstract'] = plain(a.get('body', ''))
    sdir = os.path.join(data_dir, 'sorting')
    sess = S.read_csv(os.path.join(sdir, 'sessions.csv'))
    assign = S.read_csv(os.path.join(sdir, 'assignments.csv'))
    moves = S.read_csv(os.path.join(sdir, 'moves.csv')) if os.path.exists(os.path.join(sdir, 'moves.csv')) else []
    by_session = collections.defaultdict(list)
    for a in assign:
        if a['session_id'] and talks[a['talk_id']]['status'] == 'active':
            by_session[a['session_id']].append(a)
    for v in by_session.values():
        v.sort(key=lambda a: int(a['order']))
    for s in sess:
        s['talks'] = [a['talk_id'] for a in by_session[s['session_id']]]
        s['used'] = sum(int(talks[i]['minutes']) for i in s['talks'])
    lonely = [a for a in assign if not a['session_id'] and talks[a['talk_id']]['status'] == 'active']
    return talks, cards, sess, assign, lonely, moves


def content_hash(area, sess, talks):
    rows = [(s['session_id'], s['title'], s['minutes'], s['size'], *s['talks']) for s in sess if s['area'] == area]
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:10]


def summary(cards, i):
    return (cards.get(i) or {}).get('key_claim', '')


def plain(text):
    """An abstract as readable text in a cell: HTML tags dropped, entities decoded, at most a cell's 50,000 characters."""
    t = html.unescape(re.sub(r'<br\s*/?>|</p>', '\n', text or '', flags=re.I))
    return re.sub(r'<[^>]+>', '', t).strip()[:50000]


def clip_req(sheet_id, col):
    """Show only the start of a long cell (no wrapping, no spill); the full text is there when the cell is opened."""
    return {'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'startColumnIndex': col, 'endColumnIndex': col + 1},
                           'cell': {'userEnteredFormat': {'wrapStrategy': 'CLIP'}}, 'fields': 'userEnteredFormat.wrapStrategy'}}


FIT_COLORS = ({'red': 0.97, 'green': 0.41, 'blue': 0.42}, {'red': 1.0, 'green': 0.92, 'blue': 0.52},
              {'red': 0.45, 'green': 0.62, 'blue': 0.85})     # red, yellow, blue: low, middle and top of pack.FIT_RANGE


def fit_rule(sheet_id, col):
    """The Fit column: three decimals, coloured red (poor fit) through yellow to blue (good fit) over pack.FIT_RANGE."""
    lo, hi = pack.FIT_RANGE
    point = lambda c, v: {'color': c, 'type': 'NUMBER', 'value': str(round(v, 3))}
    rng = {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'startColumnIndex': col, 'endColumnIndex': col + 1}
    return [{'repeatCell': {'range': rng, 'cell': {'userEnteredFormat': {'numberFormat': {'type': 'NUMBER', 'pattern': '0.000'}}},
                            'fields': 'userEnteredFormat.numberFormat'}},
            {'addConditionalFormatRule': {'index': 0, 'rule': {'ranges': [rng], 'gradientRule': {
                'minpoint': point(FIT_COLORS[0], lo), 'midpoint': point(FIT_COLORS[1], (lo + hi) / 2), 'maxpoint': point(FIT_COLORS[2], hi)}}}}]


# ---------- sheet building ----------
def color_req(sheet_id, r0, r1, c0, c1, color):
    return {'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': r0, 'endRowIndex': r1, 'startColumnIndex': c0,
                                     'endColumnIndex': c1},
                           'cell': {'userEnteredFormat': {'backgroundColor': color}}, 'fields': 'userEnteredFormat.backgroundColor'}}


def tab_requests(sheet_id, n_rows, widths, wrap_cols=(), notes_cols=()):
    """Frozen bold header, column widths, wrapped columns, tinted notes columns."""
    reqs = [{'updateSheetProperties': {'properties': {'sheetId': sheet_id, 'gridProperties': {'frozenRowCount': HEADER_ROW}},
                                       'fields': 'gridProperties.frozenRowCount'}},
            {'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': 0, 'endRowIndex': HEADER_ROW},
                            'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'verticalAlignment': 'BOTTOM'}},
                            'fields': 'userEnteredFormat(textFormat,verticalAlignment)'}},
            {'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW},
                            'cell': {'userEnteredFormat': {'verticalAlignment': 'TOP'}}, 'fields': 'userEnteredFormat.verticalAlignment'}}]
    for c, w in enumerate(widths):
        reqs.append({'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': c, 'endIndex': c + 1},
                                                   'properties': {'pixelSize': w}, 'fields': 'pixelSize'}})
    for c in wrap_cols:
        reqs.append({'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW - 1, 'startColumnIndex': c, 'endColumnIndex': c + 1},
                                    'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP'}}, 'fields': 'userEnteredFormat.wrapStrategy'}})
    for c in notes_cols:
        reqs.append(color_req(sheet_id, HEADER_ROW - 1, HEADER_ROW + n_rows, c, c + 1, NOTES))
    return reqs


def protect_req(sheet_id, n_rows=0, editable=()):
    """Lock a generated tab to the owner (the lead), except the editable columns of its data rows."""
    free = [{'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_rows, 'startColumnIndex': c,
             'endColumnIndex': c + 1} for c in editable if n_rows]
    return [{'addProtectedRange': {'protectedRange': {'range': {'sheetId': sheet_id}, 'unprotectedRanges': free, 'warningOnly': False,
                                                      'description': 'Generated by dqi_sort.sheets from the sort in git'}}}]


def owner_only(reqs, owner):
    """Name the owner as the only editor of every protected range in reqs. Without an explicit list, Google lets every
    editor of the file edit a protected range too, which would open the shared sheet's locked tabs to the reviewers."""
    for r in reqs:
        if 'addProtectedRange' in r and owner:
            r['addProtectedRange']['protectedRange']['editors'] = {'users': [owner]}
    return reqs


def band_requests(sheet_id, groups, n_cols, bold_rows=(), skip_cols=()):
    """Alternate a light band by session; groups is the session ID of each data row. Bold the given rows."""
    reqs, k, start = [], -1, 0
    rows = list(groups) + [None]
    for r in range(1, len(rows) + 1):
        if r == len(rows) or rows[r] != rows[start]:
            k += 1
            if k % 2 == 0 and rows[start] is not None:
                for c0, c1 in spans(n_cols, skip_cols):
                    reqs.append(color_req(sheet_id, HEADER_ROW + start, HEADER_ROW + r, c0, c1, BAND))
            start = r
    for r in bold_rows:
        reqs.append({'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW + r, 'endRowIndex': HEADER_ROW + r + 1},
                                    'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}})
    return reqs


def spans(n, skip):
    out, c0 = [], 0
    for c in sorted(skip) + [n]:
        if c > c0:
            out.append((c0, c))
        c0 = c + 1
    return out


def checkbox_req(sheet_id, col, n_rows):
    return {'setDataValidation': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_rows,
                                            'startColumnIndex': col, 'endColumnIndex': col + 1},
                                  'rule': {'condition': {'type': 'BOOLEAN'}}}}


def list_req(sheet_id, col, n_rows, values):
    return {'setDataValidation': {'range': {'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_rows,
                                            'startColumnIndex': col, 'endColumnIndex': col + 1},
                                  'rule': {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': v} for v in values]},
                                           'showCustomUi': True, 'strict': True}}}


def short_rule(sheet_id, n_rows, len_col, fill_col):
    """Shade the fill cell when a session has more than one empty 12-minute slot."""
    a = chr(ord('A') + fill_col)
    b = chr(ord('A') + len_col)
    r = HEADER_ROW + 1
    return {'addConditionalFormatRule': {'index': 0, 'rule': {
        'ranges': [{'sheetId': sheet_id, 'startRowIndex': HEADER_ROW, 'endRowIndex': HEADER_ROW + n_rows,
                    'startColumnIndex': fill_col, 'endColumnIndex': fill_col + 1}],
        'booleanRule': {'condition': {'type': 'CUSTOM_FORMULA', 'values': [{'userEnteredValue': f'=AND({b}{r}<>"",{a}{r}<{b}{r}-12)'}]},
                        'format': {'backgroundColor': SHORT}}}}}


class Book:
    """One spreadsheet: tabs of rows, written in three calls (structure, values, formatting)."""

    def __init__(self, title_line, owner=None):
        self.title_line, self.tabs, self.top, self.owner = title_line, [], {}, owner

    def tab(self, name, header, rows, fmt, top=None):
        """fmt(sheet_id, n_rows) -> formatting requests; top: more cells for row 1, after the title in A1."""
        self.tabs.append((name, header, rows, fmt))
        if top:
            self.top[name] = top

    def write(self, sheets, spreadsheet_id, fresh):
        meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id,
                                         fields='sheets(properties(sheetId,title),conditionalFormats,protectedRanges(protectedRangeId))').execute(num_retries=5)
        have = {s['properties']['title']: s for s in meta['sheets']}
        reqs, ids = [], {}
        first = meta['sheets'][0]['properties']['sheetId']
        for k, (name, *_rest) in enumerate(self.tabs):
            if name in have:
                sid = have[name]['properties']['sheetId']
                reqs.append({'updateCells': {'range': {'sheetId': sid}, 'fields': '*'}})
                reqs.append({'unmergeCells': {'range': {'sheetId': sid}}})          # the area sheets' comment box
                reqs += [{'deleteConditionalFormatRule': {'sheetId': sid, 'index': 0}} for _ in have[name].get('conditionalFormats', [])]
                reqs += [{'deleteProtectedRange': {'protectedRangeId': p['protectedRangeId']}} for p in have[name].get('protectedRanges', [])]
            elif fresh and k == 0:
                sid = first
                reqs.append({'updateSheetProperties': {'properties': {'sheetId': sid, 'title': name}, 'fields': 'title'}})
            else:
                sid = 1000 + k
                reqs.append({'addSheet': {'properties': {'sheetId': sid, 'title': name, 'index': k}}})
            ids[name] = sid
        sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={'requests': reqs}).execute(num_retries=5)
        data = [{'range': f"'{name}'!A1", 'values': [[f'{self.title_line}'] + self.top.get(name, [])] + [header] + rows}
                for name, header, rows, _ in self.tabs]
        sheets.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id,
                                                   body={'valueInputOption': 'USER_ENTERED', 'data': data}).execute(num_retries=5)
        fmt = owner_only([r for name, header, rows, f in self.tabs for r in f(ids[name], len(rows))], self.owner)
        sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={'requests': fmt}).execute(num_retries=5)


# ---------- the two kinds of sheet ----------
def estimate_cells(est, s):
    e = est.get(s['session_id'])
    if not e:
        return ['', '']
    return [f"{e['interest']} ({e['low']}-{e['high']})", e['size'] + (f" ({e['size_note']})" if e.get('size_note') else '')]


def comments_requests(sid):
    """Row 1 of an area sheet's Session summary: the title over A-E, a highlighted label in F, the comment box over G-I."""
    rng = lambda c0, c1: {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1, 'startColumnIndex': c0, 'endColumnIndex': c1}
    fmt = lambda c0, c1, f, fields: {'repeatCell': {'range': rng(c0, c1), 'cell': {'userEnteredFormat': f}, 'fields': f'userEnteredFormat({fields})'}}
    box = {'style': 'SOLID_MEDIUM', 'color': {'red': 0.8, 'green': 0.55, 'blue': 0.0}}
    return [{'mergeCells': {'range': rng(0, COMMENTS_COL - 1), 'mergeType': 'MERGE_ALL'}},
            {'mergeCells': {'range': rng(COMMENTS_COL, COMMENTS_COL + 3), 'mergeType': 'MERGE_ALL'}},
            {'updateDimensionProperties': {'range': {'sheetId': sid, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
                                           'properties': {'pixelSize': 120}, 'fields': 'pixelSize'}},
            fmt(0, COMMENTS_COL + 3, {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP'}, 'wrapStrategy,verticalAlignment'),
            fmt(COMMENTS_COL - 1, COMMENTS_COL, {'backgroundColor': HIGHLIGHT, 'textFormat': {'bold': True}}, 'backgroundColor,textFormat'),
            fmt(COMMENTS_COL, COMMENTS_COL + 3, {'backgroundColor': NOTES, 'textFormat': {'bold': False}}, 'backgroundColor,textFormat'),
            {'updateBorders': {'range': rng(COMMENTS_COL, COMMENTS_COL + 3), 'top': box, 'bottom': box, 'left': box, 'right': box}}]


def area_book(area, name, rnd, stamp_text, sess, talks, cards, est, options, fit=None):
    fit = fit or {}
    b = Book(f'{area}: {name}. Round {rnd}. {stamp_text}')
    mine = [s for s in sess if s['area'] == area]
    srows, groups, bold = [], [], []
    for s in mine:
        for k, i in enumerate(s['talks'], 1):
            t = talks[i]
            r = HEADER_ROW + 1 + len(srows)
            srows.append([s['session_id'], f"=IFERROR(VLOOKUP(A{r},'Session summary'!$A:$B,2,FALSE),\"\")", k, i, t['title'],
                          t['speaker'], t['institution'] or t['affiliation'], int(t['minutes']), fit.get(i, ''), summary(cards, i),
                          t.get('abstract', ''), False, ''])
            groups.append(s['session_id'])
            if t['type'] == 'invited':
                bold.append(len(srows) - 1)
    first, last = HEADER_ROW + 1, HEADER_ROW + max(1, len(srows))
    rows = []
    for n, s in enumerate(mine):
        r = HEADER_ROW + 1 + n
        filled = f"=SUMIFS(Sessions!$H${first}:$H${last},Sessions!$A${first}:$A${last},A{r},Sessions!$L${first}:$L${last},FALSE)"
        rows.append([s['session_id'], s['title'], s['kind'], int(s['minutes']), filled, *estimate_cells(est, s), s['size'], s['notes']])
    b.tab('Session summary',
          ['Session', 'Title', 'Type', 'Length (min)', 'Filled (min)', 'Est. peak attendance', 'Suggested room', 'Room size override', 'Notes'],
          rows, lambda sid, n: tab_requests(sid, n, [80, 340, 110, 90, 90, 100, 150, 120, 320], wrap_cols=[1, 8], notes_cols=[7, 8])
          + [short_rule(sid, n, 3, 4), list_req(sid, 7, n, SIZES)] + comments_requests(sid),
          top=[''] * (COMMENTS_COL - 2) + [COMMENTS_LABEL, ''])
    b.tab('Sessions',
          ['Session', 'Session title', 'Order', 'Talk ID', 'Title', 'Speaker', 'Institution', 'Minutes', 'Fit', 'Summary', 'Abstract',
           'Move to lonely abstracts', 'Notes'],
          srows, lambda sid, n: tab_requests(sid, n, [80, 200, 50, 75, 330, 150, 180, 65, 55, 380, 380, 100, 260], wrap_cols=[1, 4, 6, 9, 12], notes_cols=[12])
          + [clip_req(sid, 10)] + band_requests(sid, groups, 13, bold, skip_cols=[12]) + [checkbox_req(sid, 11, n)] + fit_rule(sid, 8))
    if options:
        orows, og = [], []
        for o in options:
            for i in o['talks']:
                t = talks[i]
                orows.append([o['option'], o['replaces'], o['session_id'], o['title'], int(o['minutes']), o['order'][i], i, t['title'],
                              t['institution'] or t['affiliation'], o['why']])
                og.append(o['session_id'])
        b.tab('Options', ['Option', 'Replaces', 'Session', 'Session title', 'Length (min)', 'Order', 'Talk ID', 'Title', 'Institution', 'Why'],
              orows, lambda sid, n: tab_requests(sid, n, [60, 140, 110, 260, 80, 50, 75, 330, 180, 300], wrap_cols=[3, 7, 9])
              + band_requests(sid, og, 10))
    return b


ASSIGN_TAB = 'Area assignments'
ASSIGN_COLS = ['Area', 'Name', 'Area sheet', 'Round', 'Sessions', 'Talks', 'Responsible', 'Status', 'Sheet made']
EDITABLE = (6, 7)                                     # Responsible, Status: the only cells others may edit


def read_assignments(sheets, spreadsheet_id):
    """{area: (responsible, status)} as typed into the shared sheet's assignments tab ({} if there is none yet)."""
    try:
        vals = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{ASSIGN_TAB}'!A{HEADER_ROW + 1}:H500").execute(num_retries=5)
    except Exception:
        return {}
    out = {}
    for r in vals.get('values', []):
        r = r + [''] * (8 - len(r))
        if r[0]:
            out[r[0]] = (r[6].strip(), r[7].strip())
    return out


def shared_book(year_name, stamp_text, sess, talks, cards, est, lonely, moves, area_rows=(), fit=None, owner=None):
    fit = fit or {}
    b = Book(f'{year_name}: the whole sort. {stamp_text}', owner)
    b.tab(ASSIGN_TAB, ASSIGN_COLS, [list(r) for r in area_rows],
          lambda sid, n: tab_requests(sid, n, [70, 300, 170, 60, 70, 60, 180, 360, 130], wrap_cols=[1, 7], notes_cols=EDITABLE)
          + protect_req(sid, n, EDITABLE))
    rows = [[s['session_id'], s['area'], s['title'], s['kind'], int(s['minutes']), s['used'], *estimate_cells(est, s), s['size']]
            for s in sess]
    short = [k for k, s in enumerate(sess) if s['used'] < int(s['minutes']) - 12]
    b.tab('Session summary', ['Session', 'Area', 'Title', 'Type', 'Length (min)', 'Filled (min)', 'Est. peak attendance', 'Suggested room', 'Room size'],
          rows, lambda sid, n: tab_requests(sid, n, [80, 70, 340, 110, 90, 90, 100, 150, 90], wrap_cols=[2]) + protect_req(sid)
          + [color_req(sid, HEADER_ROW + k, HEADER_ROW + k + 1, 5, 6, SHORT) for k in short])
    srows, groups, bold = [], [], []
    for s in sess:
        for k, i in enumerate(s['talks'], 1):
            t = talks[i]
            srows.append([s['session_id'], s['title'], k, i, t['title'], t['speaker'], t['institution'] or t['affiliation'],
                          int(t['minutes']), fit.get(i, ''), summary(cards, i), t.get('abstract', '')])
            groups.append(s['session_id'])
            if t['type'] == 'invited':
                bold.append(len(srows) - 1)
    b.tab('Sessions', ['Session', 'Session title', 'Order', 'Talk ID', 'Title', 'Speaker', 'Institution', 'Minutes', 'Fit', 'Summary', 'Abstract'],
          srows, lambda sid, n: tab_requests(sid, n, [80, 200, 50, 75, 330, 150, 180, 65, 55, 380, 380], wrap_cols=[1, 4, 6, 9]) + [clip_req(sid, 10)]
          + protect_req(sid) + band_requests(sid, groups, 11, bold) + fit_rule(sid, 8))
    lrows = [[a['talk_id'], talks[a['talk_id']]['area'], talks[a['talk_id']]['type'], talks[a['talk_id']]['title'],
              talks[a['talk_id']]['speaker'], talks[a['talk_id']]['institution'], summary(cards, a['talk_id']), a['note']]
             for a in sorted(lonely, key=lambda a: (talks[a['talk_id']]['area'], S.id_key(a['talk_id'])))]
    b.tab('Lonely abstracts', ['Talk ID', 'Area', 'Type', 'Title', 'Speaker', 'Institution', 'Summary', 'Note'],
          lrows, lambda sid, n: tab_requests(sid, n, [75, 70, 60, 330, 150, 180, 380, 380], wrap_cols=[3, 5, 6, 7]) + protect_req(sid))
    mrows = [[m['when'], m['talk_id'], talks.get(m['talk_id'], {}).get('title', ''), m['from'], m['to'], m['by'], m['reason']] for m in moves]
    b.tab('Moves', ['When', 'Talk ID', 'Title', 'From', 'To', 'By', 'Reason'],
          mrows, lambda sid, n: tab_requests(sid, n, [90, 75, 330, 90, 90, 70, 420], wrap_cols=[2, 6]) + protect_req(sid))
    return b


def reissuable(todo, last, applied, status):
    """Areas of todo whose current round can be rewritten in place: it exists, is not read back, and has no Status."""
    return [a for a in todo if a in last and (a, last[a]['round']) not in applied and not status.get(a, ('', ''))[1]]


def read_options(data_dir, sess):
    out = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(data_dir, 'sorting', 'options', '*', 'option*.csv'))):
        area = os.path.basename(os.path.dirname(path))
        opt = os.path.splitext(os.path.basename(path))[0].replace('option', '')
        by = collections.OrderedDict()
        for r in S.read_csv(path):
            o = by.setdefault(r['session_id'], {'option': opt, 'replaces': r['replaces'].replace(';', ', '), 'session_id': r['session_id'],
                                                'title': r['title'], 'minutes': r['minutes'], 'why': r['why'], 'talks': [], 'order': {}})
            o['talks'].append(r['talk_id'])
            o['order'][r['talk_id']] = int(r['order'])
        out[area] += list(by.values())
    return out


# ---------- sync ----------
def held_back(todo, last, applied, status):
    """Areas that get no new round: their current round is not read back yet and someone has given it a Status."""
    return [a for a in todo if a in last and (a, last[a]['round']) not in applied and status.get(a, ('', ''))[1]]



def sync(data_dir, areas=None, all_areas=False, attendance=True, reissue=False):
    cfg = S.load_config(data_dir)
    folder = (cfg.get('sheets') or {}).get('folder_id')
    if not folder:
        sys.exit('no sheets.folder_id in config.yaml; run `python -m dqi_sort.gsheets setup` first (docs/google_sheets.md)')
    commit, stamp_text = stamp(data_dir)
    talks, cards, sess, assign, lonely, moves = load(data_dir)
    fit = pack.talk_fits(data_dir, sess)          # each talk's similarity to the rest of its session
    log_path = os.path.join(data_dir, 'sorting', 'sheets.csv')
    log = S.read_csv(log_path) if os.path.exists(log_path) else []
    names = {a: v.get('name', '') for a, v in (cfg.get('areas') or {}).items()}
    in_sort = sorted({s['area'] for s in sess})
    last = {}
    for r in log:
        if r['kind'] == 'area':
            last[r['area']] = r
    if areas:
        todo = areas
    elif all_areas:
        todo = in_sort
    else:
        todo = [a for a in in_sort if a not in last or last[a]['content'] != content_hash(a, sess, talks)]
    est = S.estimates(data_dir, [s for s in sess if s.get('area') != 'VIRTUAL'], cfg) if attendance else {}
    drive, sheets = gsheets.services()
    shared = next((r for r in reversed(log) if r['kind'] == 'shared'), None)
    status = read_assignments(sheets, shared['sheet_id']) if shared else {}      # what people typed: keep it across syncs
    rpath = os.path.join(data_dir, 'sorting', 'reviews.csv')
    applied = {(r['area'], r['round']) for r in S.read_csv(rpath)} if os.path.exists(rpath) else set()
    if not areas:                                # never replace a sheet someone is working on
        out = held_back(todo, last, applied, status)
        for a in out:
            print(f"{a}: round {last[a]['round']} is out (Status: {status[a][1]}); its changes wait for the next round")
        todo = [a for a in todo if a not in out]
    year_name = (cfg.get('sheets') or {}).get('folder_name', 'DQI sort')
    link_role = (cfg.get('sheets') or {}).get('link_sharing')      # e.g. reader: anyone with the link can view
    now = datetime.datetime.now().isoformat(timespec='minutes')

    options = read_options(data_dir, sess)
    again = set(reissuable(todo, last, applied, status)) if reissue else set()
    for area in todo:                            # area sheets first: the shared sheet links to them
        if area in again:                        # nobody has started: rewrite the current round in place
            r = last[area]
            title = f"{area} round {r['round']} ({commit})"
            area_book(area, names.get(area, ''), r['round'], stamp_text, sess, talks, cards, est, options.get(area), fit).write(sheets, r['sheet_id'], False)
            drive.files().update(fileId=r['sheet_id'], body={'name': title, 'description': stamp_text}).execute(num_retries=5)
            r.update(commit=commit, content=content_hash(area, sess, talks), made=now)
            print(f"{area} round {r['round']} rewritten in place:", r['url'])
            continue
        rnd = 1 + sum(1 for r in log if r['kind'] == 'area' and r['area'] == area)
        title = f'{area} round {rnd} ({commit})'
        aid = gsheets.create_sheet(drive, title, folder)
        prev = last.get(area)                    # a new round keeps the access of the area's previous sheet
        try:
            bodies = gsheets.new_sheet_access(drive, prev['sheet_id'] if prev else None, link_role)
        except Exception as e:                   # the previous sheet trashed or unreachable: link sharing only
            print(f'{area}: could not read the access of round {prev["round"] if prev else "?"} ({e.__class__.__name__}); link sharing only')
            bodies = gsheets.new_sheet_access(drive, None, link_role)
        res = gsheets.share(drive, aid, bodies)
        if res['emailed']:
            print(f"{area}: Drive emailed an invitation to {', '.join(res['emailed'])} (no Google account, so not added quietly)")
        for who, err in res['failed']:
            print(f'{area}: could not give {who} access to round {rnd} ({err}); share it by hand')
        area_book(area, names.get(area, ''), rnd, stamp_text, sess, talks, cards, est, options.get(area), fit).write(sheets, aid, True)
        drive.files().update(fileId=aid, body={'description': stamp_text}).execute(num_retries=5)
        log.append({'kind': 'area', 'area': area, 'round': rnd, 'commit': commit, 'content': content_hash(area, sess, talks),
                    'sheet_id': aid, 'url': gsheets.url(aid), 'made': now})
        print(f'{area} round {rnd}:', gsheets.url(aid))

    fresh = shared is None
    sid = gsheets.create_sheet(drive, f'{year_name}: shared sort', folder) if fresh else shared['sheet_id']
    if fresh:                                    # the shared sheet is updated in place after this, so its access stays
        gsheets.share(drive, sid, gsheets.new_sheet_access(drive, None, link_role))
    latest = {}
    for r in log:
        if r['kind'] == 'area':
            latest[r['area']] = r
    rows, saved = [], []
    for area in in_sort:
        r = latest.get(area)
        mine = [x for x in sess if x['area'] == area]
        resp, stat = status.get(area, ('', ''))
        if area in todo:                         # a new round starts with no status (the old one is in git)
            stat = ''
        link = f'=HYPERLINK("{r["url"]}", "{area} round {r["round"]}")' if r else ''
        rows.append([area, names.get(area, ''), link, r['round'] if r else '', len(mine), sum(len(x['talks']) for x in mine),
                     resp, stat, r['made'].replace('T', ' ') if r else ''])
        saved.append({'area': area, 'responsible': resp, 'status': stat})
    owner = drive.about().get(fields='user(emailAddress)').execute()['user']['emailAddress']
    shared_book(year_name, stamp_text, sess, talks, cards, est, lonely, moves, rows, fit, owner).write(sheets, sid, fresh)
    drive.files().update(fileId=sid, body={'description': stamp_text}).execute(num_retries=5)
    print('shared sheet:', gsheets.url(sid))
    if fresh:
        log.append({'kind': 'shared', 'area': '', 'round': '', 'commit': commit, 'content': '', 'sheet_id': sid, 'url': gsheets.url(sid), 'made': now})
    else:
        shared.update(commit=commit, made=now)
    S.write_csv(os.path.join(data_dir, 'sorting', 'area_status.csv'), ['area', 'responsible', 'status'], saved)
    S.write_csv(log_path, LOG_COLS, log)
    if not todo:
        print('no area changed since its last sheet')
    print(f'recorded in {log_path}; commit it')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['sync'])
    ap.add_argument('data_dir')
    ap.add_argument('--areas', help='comma-separated areas to make new sheets for (default: those that changed)')
    ap.add_argument('--all', action='store_true', help='make new sheets for every area')
    ap.add_argument('--reissue', action='store_true', help='rewrite in place the current round of areas nobody has started')
    ap.add_argument('--no-attendance', action='store_true')
    a = ap.parse_args()
    sync(a.data_dir, a.areas.split(',') if a.areas else None, a.all, not a.no_attendance, a.reissue)


if __name__ == '__main__':
    main()
