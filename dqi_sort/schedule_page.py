"""The schedule as one page: rooms by time blocks, coloured by expected attendance, with each session's talks.

    python -m dqi_sort.schedule_page DATA_DIR [--dry-run] [--out PATH] [--no-attendance]

Without --dry-run: the schedule in schedule/schedule.csv, written to DATA_DIR/views/schedule.html.
With --dry-run: copies the data repo's HEAD to a temporary folder, runs `schedule budget --apply` and `schedule solve`
there, and writes the page to DATA_DIR/views/schedule_dryrun.html. The real sort, room sizes and schedule are not
touched; use it to see what scheduling would do before doing it.

The page is self-contained (no network; it holds talk titles and speakers, so it belongs in the private data repo).
- Rows are time blocks, columns rooms (venue/rooms.csv), with our slots, the DQI symposia (schedule/symposia.csv:
  session_id, title, minutes, day, start, end, room_id, block) and hatched cells for blocks that are not ours.
- Thermometer colours (ColorBrewer YlOrRd on a log scale, 30 to 600 people): each session by its estimated peak
  attendance (the attendance model, spread-matched as in the review sheets; symposia ranked against past symposia),
  each room heading by its seats, so a session hotter than its heading may be short of seats. Under the headings, a
  line per room on what it holds (its main topic family and share, the review areas, its symposia), to check that
  rooms keep a theme. ▲ marks a session whose
  high estimate exceeds the seats. Badges: MS mini-symposium, SYM symposium, REC recorded room.
- Click a session for its scope, coherence, estimate and talks (with each talk's fit chip, pack.FIT_RANGE colours).
Needs Ollama for the estimates (`--no-attendance` leaves them out).
"""
import argparse, collections, io, json, os, subprocess, sys, tarfile, tempfile
import numpy as np

from dqi_sort import sessions as S, pack, sheets

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'schedule_page.html')
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']


def symposium_estimates(data_dir, sym):
    """{session_id: (interest, low, high)}: the model's ranking of the symposia, mapped onto past symposium peaks."""
    from dqi_sort import attendance
    model = attendance.load(data_dir)
    res = model.interest([x['title'] for x in sym], ['symposium'] * len(sym),
                         attendance.ollama_embed([attendance.session_text(x['title'], 'symposium') for x in sym]))
    past = np.sort([r['peak'] for r in attendance.read_history(data_dir) if r['type'] == 'symposium'])
    out = {}
    if len(res) >= 5 and len(past):
        order = np.argsort([r['interest'] for r in res], kind='stable')
        rank = np.empty(len(res)); rank[order] = np.arange(len(res))
        for r, k in zip(res, rank):
            m = float(np.quantile(past, (k + 0.5) / len(res))); f = m / max(1, r['interest'])
            r.update(interest=round(m), low=round(r['low'] * f), high=round(r['high'] * f))
    for x, r in zip(sym, res):
        out[x['session_id']] = (r['interest'], r['low'], r['high'])
    return out


def collect(data_dir, attendance=True):
    cfg = S.load_config(data_dir)
    talks, cards, sess, *_ = sheets.load(data_dir)
    by = {s['session_id']: s for s in sess}
    space = pack.Space(data_dir, None)
    rooms = S.read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))
    slots = {x['slot_id']: x for x in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
    sched = {r['session_id']: r['slot_id'] for r in S.read_csv(os.path.join(data_dir, 'schedule', 'schedule.csv'))}
    spath = os.path.join(data_dir, 'schedule', 'symposia.csv')
    sym = S.read_csv(spath) if os.path.exists(spath) else []
    est, sest = {}, {}
    if attendance:
        est = S.estimates(data_dir, [s for s in sess if s['area'] != 'VIRTUAL'], cfg)
        try:
            sest = symposium_estimates(data_dir, sym) if sym else {}
        except Exception as e:
            print(f'no symposium estimates ({e.__class__.__name__}: {e})')
    cells = []
    for sid, slot in sched.items():
        if sid not in by or slot not in slots:
            continue
        x, s = slots[slot], by[sid]
        coh, per = pack.coherence(space, s['talks'])
        e = est.get(sid) or {}
        cells.append({'kind': 'ours', 'id': sid, 'title': s['title'], 'area': s['area'], 'type': s['kind'], 'minutes': int(s['minutes']),
                      'size': s.get('size', ''), 'day': x['day'], 'start': x['start'], 'room': x['room_id'], 'track': x['track'],
                      'est': e.get('interest'), 'low': e.get('low'), 'high': e.get('high'), 'coh': round(coh, 3), 'scope': s.get('scope', ''),
                      'talks': [{'t': sheets.plain(talks[i]['title']), 'sp': talks[i]['speaker'], 'inv': talks[i]['type'] == 'invited',
                                 'fit': round(per.get(i, 0), 3)} for i in s['talks']]})
    for x in sym:
        i, lo, hi = sest.get(x['session_id'], (None, None, None))
        cells.append({'kind': 'symposium', 'id': x['session_id'], 'title': x['title'], 'type': 'symposium', 'minutes': int(x['minutes']),
                      'day': x['day'], 'start': x['start'], 'room': x['room_id'], 'track': 'in_person', 'est': i, 'low': lo, 'high': hi})
    ip = [x for x in slots.values() if x['track'] == 'in_person']
    blocks = sorted({(x['day'], x['start'], x['end'], int(x['minutes']), x.get('block', '')) for x in ip},
                    key=lambda b: (DAYS.index(b[0]), b[1]))
    open_ = {f"{x['day']}|{x['start']}|{x['room_id']}" for x in ip} | {f"{x['day']}|{x['start']}|{x['room_id']}" for x in sym}
    return {'rooms': [{'id': r['room_id'], 'name': r['name'], 'cap': int(r['capacity']), 'size': r['size'], 'rec': S.is_recorded(r)} for r in rooms],
            'blocks': [{'day': b[0], 'start': b[1], 'end': b[2], 'minutes': b[3], 'code': b[4]} for b in blocks],
            'open': sorted(open_), 'cells': cells, 'time_zone': cfg.get('time_zone', ''), 'room_desc': room_descriptions(cells, cfg)}


def room_descriptions(cells, cfg):
    """{room_id: one line on what the room holds}: its main topic family (an area's `modality` in config.yaml, else the
    area) with its share of the room's sessions, then the review areas by count, and the symposia it has."""
    areas_cfg = cfg.get('areas') or {}
    fam = lambda a: (areas_cfg.get(a) or {}).get('modality') or a
    by_room = collections.defaultdict(list)
    for c in cells:
        if c['track'] == 'in_person':
            by_room[c['room']].append(c)
    out = {}
    for r, cs in by_room.items():
        ours = [c for c in cs if c['kind'] == 'ours']
        parts = []
        if ours:
            f, n = collections.Counter(fam(c['area']) for c in ours).most_common(1)[0]
            parts.append(f"{f} {n} of {len(ours)}")
            parts.append(', '.join(f'{a} {k}' for a, k in collections.Counter(c['area'] for c in ours).most_common()))
        nsym = sum(c['kind'] == 'symposium' for c in cs)
        if nsym:
            parts.append(f'{nsym} DQI symposi{"um" if nsym == 1 else "a"}')
        out[r] = ': '.join(parts[:2]) + ('; ' + parts[2] if len(parts) > 2 else '') if ours else (parts[0] if parts else '')
    return out


def render(data):
    with open(TEMPLATE, encoding='utf-8') as f:
        page = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    return page.replace('__TITLE__', data['title']).replace('__DATA__', blob)


def head(data_dir):
    return subprocess.run(['git', '-C', data_dir, 'rev-parse', '--short=7', 'HEAD'], capture_output=True, text=True).stdout.strip()


def write(data_dir, out=None, attendance=True, dry_run=False, source=None):
    """Render the schedule in `source` (default data_dir) to out (default DATA_DIR/views/schedule.html)."""
    cfg = S.load_config(data_dir)
    year = ''.join(c for c in str(cfg.get('meeting_dates', '')) if c.isdigit())[-4:]
    data = collect(source or data_dir, attendance)
    data.update(commit=head(data_dir), dry_run=dry_run, title=f"DQI {year} schedule" + (' — dry run' if dry_run else ''))
    out = out or os.path.join(data_dir, 'views', 'schedule_dryrun.html' if dry_run else 'schedule.html')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(render(data))
    print('wrote', out)
    return out


def dry_run(data_dir, out=None, attendance=True, iters=400000, seed=1):
    """Budget and solve on a copy of the data repo's HEAD, then render it into data_dir's views."""
    from dqi_sort import schedule
    with tempfile.TemporaryDirectory() as tmp:
        tar = subprocess.run(['git', '-C', data_dir, 'archive', 'HEAD'], capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(tmp, filter='data')
        schedule.budget(tmp, apply=True)
        schedule.solve(tmp, iters=iters, seed=seed)
        return write(data_dir, out, attendance, dry_run=True, source=tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--dry-run', action='store_true', help='budget and solve on a copy of HEAD first; the real data is not touched')
    ap.add_argument('--out')
    ap.add_argument('--iters', type=int, default=400000)
    ap.add_argument('--no-attendance', action='store_true')
    a = ap.parse_args()
    if a.dry_run:
        dry_run(a.data_dir, a.out, not a.no_attendance, a.iters)
    else:
        if not os.path.exists(os.path.join(a.data_dir, 'schedule', 'schedule.csv')):
            sys.exit('no schedule/schedule.csv yet: run `schedule solve` (or use --dry-run)')
        write(a.data_dir, a.out, not a.no_attendance)


if __name__ == '__main__':
    main()
