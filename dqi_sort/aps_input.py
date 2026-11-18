"""APS's sorting sheet and volunteer-chair sheet in, read-only: the inputs for intake and for chair recruiting.

    python -m dqi_sort.aps_input check      DATA_DIR             (first, each year: is APS's sheet what we expect?)
    python -m dqi_sort.aps_input pull       DATA_DIR             (APS's live sheet -> snapshot + intake inputs)
    python -m dqi_sort.aps_input xlsx       DATA_DIR FILE.xlsx   (the same from a downloaded .xlsx)
    python -m dqi_sort.aps_input diff       DATA_DIR [OLD NEW]   (what APS changed: snapshot dates YYYYMMDD)
    python -m dqi_sort.aps_input volunteers DATA_DIR             (APS's volunteer-chair sheet -> chair_volunteers CSV)

Config (DATA_DIR/config.yaml):

    aps_sheet:
      id: <Google Sheet ID of APS's sorting sheet for our unit>
      tabs: {in_person: In-Person Sorting, virtual: Virtual Sorting, spark: SPARK Sorting}
      snapshot_prefix: SMT27_DQI          # snapshots: input/aps/<prefix>_live_<YYYYMMDD>_<track>.csv (+ T<HHMM> if
                                          # pulled twice the same day)
    aps_input: {in_person: {file: input/in_person.csv}, virtual: {file: input/virtual.csv}}
    chair_volunteer_sheet: {id: <sheet ID>, tab: Quantum Realm, out: input/chairs/volunteers_live.csv}

Tabs are found by name; a tab name that ends in "*" matches every tab starting with it (APS split the in-person talks
over six "In-Person N · topic" tabs in early 2027 and merged them into one on Nov 12). In each tab the talk table is
found by its header row (first cell "ID", a "Title" column); columns are kept as APS names them, plus Tab.

check   reads the live sheet and reports, before anything is built: the tabs found and the talks on each, the header
        columns against config aps_columns (mapped columns missing, new columns), categories not in dqi_categories,
        types not in aps_types, talks on two tabs, and a SPARK tab with talks (decide those first). Exit 1 on a problem.
pull    saves a dated snapshot of each tab as received in input/aps/, then writes the intake inputs (aps_input files):
        every row, sorted by ID, with Session, Order and Sorter Notes blanked (on the Virtual tab they are our own
        entries). Then run `python -m dqi_sort.intake DATA_DIR`, and `diff` to see what APS changed.
diff    compares two snapshots per track (default: the two newest): talks added, gone, and changed (presenter,
        title, category, type, notes). This is the "check APS's sheet for changes" step of each round.
volunteers  writes APS's volunteer chairs for our unit (the tab named in config) as the CSV chairs.py reads.
Personal data: everything written stays in the private data folder.
"""
import argparse, csv, datetime, glob, os, re, sys
from dqi_sort import sessions as S

DEFAULT_TABS = {'in_person': 'In-Person*', 'virtual': 'Virtual*', 'spark': 'SPARK*'}
OURS = ('Session', 'Order', 'Sorter Notes')        # columns sorters fill in: blanked in the intake inputs
WATCH = ('Presenter', 'Affiliation', 'Title', 'Category', 'Type', 'Special Instructions', 'Sorter Notes')


def text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def table(values):
    """(header, rows as dicts) of a tab's talk table: the header row starts with ID and has a Title column."""
    hi = next((i for i, r in enumerate(values) if r and text(r[0]) == 'ID' and 'Title' in [text(c) for c in r]), None)
    if hi is None:
        return [], []
    header = [text(c) for c in values[hi]]
    while header and not header[-1]:
        header.pop()
    rows = []
    for r in values[hi + 1:]:
        cells = [text(c) for c in r][:len(header)]
        if cells and cells[0].isdigit():
            rows.append(dict(zip(header, cells + [''] * (len(header) - len(cells)))))
    return header, rows


def cfg_sheet(cfg):
    a = cfg.get('aps_sheet') or {}
    return a.get('id'), {**DEFAULT_TABS, **(a.get('tabs') or {})}, a.get('snapshot_prefix') or 'aps'


def match(name, pattern):
    return name.startswith(pattern[:-1]) if pattern.endswith('*') else name == pattern


def read_tracks(tab_values, tabs):
    """{track: (header, rows)} from {tab name: cell values}, every row tagged with its Tab."""
    out = {}
    for track, pat in tabs.items():
        header, rows = [], []
        for name, values in tab_values.items():
            if match(name, pat):
                h, r = table(values)
                for x in r:
                    x['Tab'] = name
                header = header or h
                rows += r
        out[track] = (header, rows)
    return out


def live_values(sheet_id, tabs):
    from dqi_sort import gsheets
    _, sheets = gsheets.services()
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id, fields='sheets.properties.title').execute(num_retries=5)
    names = [s['properties']['title'] for s in meta['sheets']]
    want = [n for n in names if any(match(n, p) for p in tabs.values())]
    out = {}
    for n in want:
        out[n] = sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{n}'!A1:Z6000").execute(num_retries=5).get('values', [])
    return names, out


def xlsx_values(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return wb.sheetnames, {n: [list(r) for r in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}


def problems(tracks, cfg):
    """Format problems (strings) in what was read, against the config."""
    out = []
    colmap = {k.strip() for k in (cfg.get('aps_columns') or {})}
    types = set(cfg.get('aps_types') or {})
    cats = set(str(c) for c in (cfg.get('dqi_categories') or {}))
    seen = {}
    for track, (header, rows) in tracks.items():
        if track == 'spark':
            if rows:
                out.append(f'SPARK tab has {len(rows)} talks: decide where they go before building the inputs')
            continue
        if not header:
            out.append(f'{track}: no tab with a talk table (looked for {track} tabs; set aps_sheet.tabs)')
            continue
        miss = sorted(c for c in colmap if c not in header and not (track == 'in_person' and 'Virtual' in c))
        if miss:
            out.append(f"{track}: columns in config aps_columns but not on APS's sheet: {', '.join(miss)}")
        for r in rows:
            if r['ID'] in seen:
                out.append(f"talk {r['ID']} is on both {seen[r['ID']]} and {r['Tab']}")
            seen[r['ID']] = r['Tab']
        bad = sorted({r.get('Type', '') for r in rows} - types) if types else []
        if bad:
            out.append(f"{track}: types not in config aps_types: {', '.join(bad)}")
    return out


def notes(tracks, cfg):
    """Things to know that are not problems: new columns, categories that are not ours."""
    out = []
    colmap = {k.strip() for k in (cfg.get('aps_columns') or {})}
    cats = set(str(c) for c in (cfg.get('dqi_categories') or {}))
    for track, (header, rows) in tracks.items():
        if track == 'spark' or not header:
            continue
        tabs = sorted({r['Tab'] for r in rows})
        out.append(f"{track}: {len(rows)} talks on {', '.join(tabs) or '(none)'}")
        new = [h for h in header if h and h not in colmap]
        if new:
            out.append(f"{track}: columns not mapped (ignored by intake): {', '.join(new)}")
        if cats:
            other = sorted({r.get('Category', '') for r in rows} - cats)
            if other:
                out.append(f"{track}: categories not in dqi_categories (talks from other units?): {', '.join(other)}")
    return out


def check(data_dir, xlsx=None):
    cfg = S.load_config(data_dir)
    sheet_id, tabs, _ = cfg_sheet(cfg)
    if xlsx:
        names, vals = xlsx_values(xlsx)
    elif sheet_id:
        names, vals = live_values(sheet_id, tabs)
    else:
        sys.exit('no config aps_sheet.id (and no .xlsx given)')
    tracks = read_tracks(vals, tabs)
    print('Tabs on the sheet:', ', '.join(names))
    for line in notes(tracks, cfg):
        print(' ', line)
    probs = problems(tracks, cfg)
    for p in probs:
        print('PROBLEM', p)
    print('OK' if not probs else f'{len(probs)} problems')
    return 1 if probs else 0


def write_inputs(data_dir, cfg, tracks, snapshot=None):
    stamp = datetime.date.today().strftime('%Y%m%d')
    _, _, prefix = cfg_sheet(cfg)
    probs = [p for p in problems(tracks, cfg) if not p.startswith(('in_person: columns', 'virtual: columns'))]
    if probs:
        sys.exit('Not written:\n  ' + '\n  '.join(probs))
    for track, (header, rows) in tracks.items():
        if track == 'spark':
            continue
        if snapshot:
            p = os.path.join(data_dir, 'input', 'aps', f'{prefix}_live_{stamp}_{track}.csv')
            if os.path.exists(p):                     # a second pull the same day keeps the first: add the time
                p = p.replace(f'_live_{stamp}_', f"_live_{stamp}T{datetime.datetime.now():%H%M}_")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, header, extrasaction='ignore', lineterminator='\n')
                w.writeheader()
                w.writerows(rows)
            print(f'  {track}: {len(rows)} talks, snapshot {os.path.relpath(p, data_dir)}')
        spec = (cfg.get('aps_input') or {}).get(track) or {'file': f'input/{track}.csv'}
        out = os.path.join(data_dir, spec['file'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cols = ['Tab'] + [h for h in header if h != 'Tab']
        with open(out, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, cols, extrasaction='ignore', lineterminator='\n')
            w.writeheader()
            for r in sorted(rows, key=lambda r: (len(r['ID']), r['ID'])):
                w.writerow({**r, **{c: '' for c in OURS if c in r}})
        print(f'{len(rows)} talks -> {spec["file"]}')
    print(f'Next: python -m dqi_sort.intake {data_dir}; python -m dqi_sort.aps_input diff {data_dir}')


def pull(data_dir):
    cfg = S.load_config(data_dir)
    sheet_id, tabs, _ = cfg_sheet(cfg)
    if not sheet_id:
        sys.exit('set aps_sheet.id in config.yaml (the Google Sheet ID of APS\'s sorting sheet)')
    _, vals = live_values(sheet_id, tabs)
    write_inputs(data_dir, cfg, read_tracks(vals, tabs), snapshot=True)


def from_xlsx(data_dir, path):
    cfg = S.load_config(data_dir)
    _, tabs, _ = cfg_sheet(cfg)
    _, vals = xlsx_values(path)
    write_inputs(data_dir, cfg, read_tracks(vals, tabs))


def compare(old, new):
    """Lines describing what changed from old to new ({ID: row})."""
    out = [f"  added   {i} {new[i].get('Presenter', '')} | {new[i].get('Title', '')[:70]}" for i in sorted(set(new) - set(old))]
    out += [f"  gone    {i} {old[i].get('Presenter', '')} | {old[i].get('Title', '')[:70]}" for i in sorted(set(old) - set(new))]
    for i in sorted(set(old) & set(new)):
        d = [c for c in WATCH if old[i].get(c, '') != new[i].get(c, '')]
        if d:
            out.append(f"  changed {i} {new[i].get('Presenter', '')}: " + '; '.join(f'{c}: "{old[i].get(c, "")[:40]}" -> "{new[i].get(c, "")[:40]}"' for c in d))
    return out


def snapshots(data_dir, track):
    return sorted(glob.glob(os.path.join(data_dir, 'input', 'aps', f'*_live_*_{track}.csv')),
                  key=lambda p: re.search(r'_live_(\d{8}(?:T\d{4})?)_', p).group(1))


def diff(data_dir, old=None, new=None):
    """Per track, the snapshots of dates old and new (YYYYMMDD; default the two newest) compared."""
    for track in ('in_person', 'virtual'):
        snaps = snapshots(data_dir, track)
        if old and new:
            pair = [p for d in (old, new) for p in snaps if f'_live_{d}_' in p][:2]
        else:
            pair = snaps[-2:]
        if len(pair) < 2:
            print(f'{track}: fewer than two snapshots')
            continue
        a, b = ({r['ID']: r for r in S.read_csv(p)} for p in pair)
        lines = compare(a, b)
        print(f"{track}: {os.path.basename(pair[0])} -> {os.path.basename(pair[1])}: {len(a)} -> {len(b)} talks, "
              f"{len(lines)} differences")
        if lines:
            print('\n'.join(lines))


VOL_COLS = ['Sub-category', 'First name', 'Last name', 'Email', 'Affiliation', 'Chairing method', "Speaker's presentation",
            'Abstract ID', 'Chosen', 'APS notes', 'Unit', 'Country']


def volunteers(data_dir):
    """APS's live volunteer-chair tab for our unit -> the CSV chairs.py reads (config chair_volunteers)."""
    cfg = S.load_config(data_dir)
    v = cfg.get('chair_volunteer_sheet') or {}
    if not v.get('id') or not v.get('tab'):
        sys.exit('set chair_volunteer_sheet: {id: ..., tab: ..., out: ...} in config.yaml')
    from dqi_sort import gsheets
    _, s = gsheets.services()
    vals = s.spreadsheets().values().get(spreadsheetId=v['id'], range=f"'{v['tab']}'!A1:P3000").execute(num_retries=5).get('values', [])
    hi = next(i for i, r in enumerate(vals) if 'Email' in r and 'Presenter' in r)
    hdr = vals[hi]
    rows = [dict(zip(hdr, r + [''] * (len(hdr) - len(r)))) for r in vals[hi + 1:] if len(r) > 5 and r[5].strip()]
    vpath = os.path.join(data_dir, ((cfg.get('aps_input') or {}).get('virtual') or {}).get('file', 'input/virtual.csv'))
    virtual = {r['ID'] for r in S.read_csv(vpath)} if os.path.exists(vpath) else set()
    out = [{'Sub-category': r.get('Sub-category', ''), 'First name': r.get('Presenter', ''), 'Last name': '', 'Email': r.get('Email', ''),
            'Affiliation': r.get('Affiliation', ''), 'Chairing method': r.get('Chair mode', ''),
            "Speaker's presentation": 'Virtual' if r.get('Abstract ID') in virtual else 'In person',
            'Abstract ID': r.get('Abstract ID', ''), 'Chosen': r.get(hdr[1], ''), 'APS notes': r.get('Notes (session / who picked)', ''),
            'Unit': r.get('Unit', ''), 'Country': r.get('Country', '')} for r in rows]
    path = os.path.join(data_dir, v.get('out') or 'input/chairs/volunteers_live.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, VOL_COLS, lineterminator='\n')
        w.writeheader()
        w.writerows(out)
    prefix = str(cfg.get('division_code', ''))
    print(f"{len(out)} volunteer rows ({sum(1 for r in out if prefix and r['Sub-category'].startswith(prefix))} ours) -> {os.path.relpath(path, data_dir)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['check', 'pull', 'xlsx', 'diff', 'volunteers'])
    ap.add_argument('data_dir')
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    if a.cmd == 'check':
        sys.exit(check(a.data_dir, a.args[0] if a.args else None))
    if a.cmd == 'pull':
        pull(a.data_dir)
    elif a.cmd == 'xlsx':
        from_xlsx(a.data_dir, a.args[0])
    elif a.cmd == 'diff':
        diff(a.data_dir, *(a.args[:2] if len(a.args) >= 2 else []))
    else:
        volunteers(a.data_dir)


if __name__ == '__main__':
    main()
