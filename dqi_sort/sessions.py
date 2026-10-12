"""Stage 5: session proposals per review area.

    python -m dqi_sort.sessions prepare DATA_DIR
    python -m dqi_sort.sessions check DATA_DIR/work/sessions/AREA/proposal.json
    python -m dqi_sort.sessions apply DATA_DIR [--replace] [--no-attendance]

prepare  splits the session grid (schedule/slots.csv) into a share for each area in proportion to its talks
         (`share`), and writes, per area, work/sessions/AREA/: cards.txt (one compact card per talk), brief.md
         (the area's numbers and limits), prompt.md (prompts/session_spec.md, filled in) and talks.json (what
         `check` needs). One Claude agent per area then reads prompt.md and writes proposal.json there.
check    validates one proposal against its area's talks and limits; prints ERROR and WARN lines, or OK.
apply    checks every area's proposal and writes the sort: sorting/sessions.csv, sorting/assignments.csv
         (released talks are lonely, with no session), sorting/moves.csv (each release), alternative splits in
         sorting/options/AREA/, and the views views/sessions.md and views/sessions/AREA.md, with each session's
         estimated attendance and suggested room size from the attendance model (needs Ollama running).

Units: an oral talk is 1 unit (12 minutes), an invited talk 3. A session holds minutes / 12 units.
"""
import argparse, collections, csv, datetime, glob, json, os, re, sys
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = os.path.join(HERE, 'prompts', 'session_spec.md')
UNIT_MIN = 12
MAX_INVITED = 2
MAX_EMPTY = 1            # empty units allowed in an in-person session
RELEASE_WARN = 0.08      # warn when an area releases more than this share of its units
WINDOW_RE = re.compile(r'\d\d:\d\d-\d\d:\d\d')


def id_key(i):
    return (len(i), i)


def read_csv(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, lineterminator='\n', extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def load_config(data_dir):
    with open(os.path.join(data_dir, 'config.yaml'), encoding='utf-8') as f:
        return yaml.safe_load(f)


def units(t):
    return int(t['minutes']) // UNIT_MIN


def windows(s):
    return set(WINDOW_RE.findall(s or ''))


# ---------- the grid ----------
def share(area_units, n144, n108):
    """Split n144 sessions of 144 minutes and n108 of 108 minutes among areas: {area: (a, b)}.

    Each area's capacity (12a + 9b units) stays close to its own units plus its part of the spare room, and
    its mix of lengths close to the grid's. Areas take every slot when that is possible."""
    total = sum(area_units.values())
    spare = 12 * n144 + 9 * n108 - total
    r = n144 / max(1, n144 + n108)
    best = {(0, 0): (0.0, [])}
    for area, u in sorted(area_units.items()):
        target = u + spare * u / max(1, total)
        opts = []
        for a in range(0, n144 + 1):
            for b in range(0, n108 + 1):
                cap = 12 * a + 9 * b
                if abs(cap - target) <= 12:
                    opts.append((a, b, (cap - target) ** 2 + 4 * (a - r * (a + b)) ** 2 + (100 if cap < u else 0)))
        nxt = {}
        for (sa, sb), (cost, picks) in best.items():
            for a, b, c in opts:
                k = (sa + a, sb + b)
                if k[0] <= n144 and k[1] <= n108 and (k not in nxt or cost + c < nxt[k][0]):
                    nxt[k] = (cost + c, picks + [(area, a, b)])
        best = nxt
    if not best:
        sys.exit('the session grid is too small for the talks')
    key = (n144, n108) if (n144, n108) in best else max(best, key=lambda k: (12 * k[0] + 9 * k[1], -best[k][0]))
    return {area: (a, b) for area, a, b in best[key][1]}


def grid(data_dir):
    slots = [s for s in read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))]
    c = collections.Counter((s['track'], int(s['minutes'])) for s in slots)
    virtual = collections.Counter(s['start'] for s in slots if s['track'] == 'virtual')
    return c[('in_person', 144)], c[('in_person', 108)], c, virtual


# ---------- prepare ----------
def card_text(t, card, series_parts):
    inv = 'INVITED' if t['type'] == 'invited' else 'oral'
    lines = [f"{t['talk_id']} | {inv} | {t['title']} | {t['speaker']}, {t['institution'] or t['affiliation']}"]
    if card:
        lines.append(f"  platform: {card['platform']} | problem: {card['problem']} | approach: {card['approach']}")
        lines.append(f"  claim: {card['key_claim']}")
        lines.append(f"  keywords: {'; '.join(card['keywords'])}")
    else:
        lines.append('  (no card: judge from the title)')
    extra = []
    if t['series']:
        extra.append(f"series {t['series']}, part {t['series_part']} of {series_parts[t['series']]}")
    if card and card.get('constraints'):
        extra.append(f"submitter request: {card['constraints']}")
    if card and card.get('other_unit'):
        o = card['other_unit']
        extra.append(f"other unit: {o.get('unit', '')} ({o.get('strength', '')})")
    if t['track'] == 'virtual':
        extra.append('windows: ' + (t['time_windows'] or 'none given'))
    if extra:
        lines.append('  ' + ' | '.join(extra))
    return '\n'.join(lines)


RULES_IN_PERSON = """- **Lengths.** A session is 144 minutes (12 units) or 108 minutes (9 units). An oral talk is 12 minutes
  (1 unit); an invited talk is 36 minutes (3 units).
- **This area's share of the grid:** at most {N144} sessions of 144 minutes and at most {N108} of 108 minutes.
  The meeting has almost no spare room, so the area's talks must go into nearly full sessions.
- **Full sessions.** Every session holds exactly its length in units, or one unit less. If a session would run
  short, change its length (a 144-minute session with three talks fewer is a full 108-minute session) or move
  talks between neighbouring sessions."""

RULES_VIRTUAL = """- **Lengths.** Every virtual session is 120 minutes: 10 units. An oral talk is 1 unit (12 minutes), an
  invited talk 3.
- **Time windows.** Each speaker lists the virtual time windows (Mountain Time) they can make. Every speaker in
  a session must share at least one window. For a speaker with no window listed, choose the window that suits
  their institution's location and record it in `assumed_windows` ({"id": "10:30-12:30"}), so the check uses it.
  Windows and how many virtual slots each has: {WINDOWS}.
- Use as few sessions as the windows allow (at most {NV}). Topic matters less than time here, but group by
  topic as far as the windows allow."""


def brief_text(area, spec, talks, limits):
    inv = sum(t['type'] == 'invited' for t in talks)
    u = sum(units(t) for t in talks)
    lines = [f"# {area}: {spec.get('name', '')}", '',
             f"{len(talks)} talks ({len(talks) - inv} oral, {inv} invited): {u} units."]
    if limits['virtual']:
        lines.append(f"Virtual track: at most {limits['max_sessions']} sessions of 120 minutes.")
    else:
        a, b = limits['n144'], limits['n108']
        lines.append(f"Share of the grid: at most {a} sessions of 144 minutes and {b} of 108 minutes "
                     f"({12 * a + 9 * b} units).")
    if spec.get('categories'):
        lines.append('')
        lines.append('The area was drawn from these DQI categories (by each card\'s best fit), plus talks whose '
                     'content placed them here: ' + ', '.join(spec['categories']) + '.')
    return '\n'.join(lines) + '\n'


def prepare(data_dir):
    cfg = load_config(data_dir)
    talks = [t for t in read_csv(os.path.join(data_dir, 'talks.csv')) if t['status'] == 'active']
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    by_area = collections.defaultdict(list)
    for t in talks:
        if not t['area']:
            sys.exit(f"talk {t['talk_id']} has no area; run areas propose first")
        by_area[t['area']].append(t)
    n144, n108, _, virtual = grid(data_dir)
    shares = share({a: sum(units(t) for t in ts) for a, ts in by_area.items() if a != 'VIRTUAL'}, n144, n108)
    series_parts = collections.Counter(t['series'] for t in talks if t['series'])
    root = os.path.join(data_dir, 'work', 'sessions')
    if glob.glob(os.path.join(root, '*', 'proposal.json')):
        sys.exit(f'proposals already exist in {root}; apply them, or move them away to start again')
    with open(PROMPT, encoding='utf-8') as f:
        spec_text = f.read()
    max_inst = cfg.get('max_same_institution', 4)
    for area, ts in sorted(by_area.items()):
        d = os.path.join(root, area)
        os.makedirs(d, exist_ok=True)
        ts.sort(key=lambda t: ((cards.get(t['talk_id']) or {}).get('best_category', ''), id_key(t['talk_id'])))
        if area == 'VIRTUAL':
            limits = {'virtual': True, 'max_sessions': sum(virtual.values()), 'minutes': [cfg.get('virtual_session_min', 120)]}
            rules = RULES_VIRTUAL.replace('{NV}', str(limits['max_sessions'])).replace(
                '{WINDOWS}', ', '.join(f'{k} ({n})' for k, n in sorted(virtual.items())))
        else:
            a, b = shares.get(area, (0, 0))
            limits = {'virtual': False, 'n144': a, 'n108': b, 'minutes': [144, 108]}
            rules = RULES_IN_PERSON.replace('{N144}', str(a)).replace('{N108}', str(b))
        limits.update(area=area, max_same_institution=max_inst)
        info = {t['talk_id']: {'type': t['type'], 'units': units(t), 'series': t['series'],
                               'part': int(t['series_part'] or 0), 'institution': t['institution'] or t['affiliation'],
                               'windows': sorted(windows(t['time_windows']))} for t in ts}
        with open(os.path.join(d, 'talks.json'), 'w', encoding='utf-8') as f:
            json.dump({'limits': limits, 'talks': info}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(d, 'cards.txt'), 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(card_text(t, cards.get(t['talk_id']), series_parts) for t in ts) + '\n')
        with open(os.path.join(d, 'brief.md'), 'w', encoding='utf-8') as f:
            f.write(brief_text(area, (cfg.get('areas') or {}).get(area, {}), ts, limits))
        check_cmd = f"cd {HERE} && .venv/bin/python -m dqi_sort.sessions check {os.path.abspath(d)}/proposal.json"
        with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
            f.write(spec_text.replace('{RULES}', rules).replace('{MAX_INST}', str(max_inst))
                    .replace('{CHECK}', check_cmd).replace('{DIR}', os.path.abspath(d)))
        cap = f"{limits['max_sessions']} virtual" if limits['virtual'] else f"{limits['n144']} x 144 + {limits['n108']} x 108"
        print(f"{area:8s} {len(ts):4d} talks {sum(units(t) for t in ts):5d} units   share: {cap}")
    print(f'grid: {n144} x 144 + {n108} x 108 in person ({12 * n144 + 9 * n108} units); files in {root}')


# ---------- check ----------
def session_problems(s, n, info, limits, assumed):
    """Errors and warnings for one session dict; n is its label."""
    err, warn = [], []
    talks = s.get('talks') or []
    if not str(s.get('title', '')).strip():
        err.append(f'{n}: no title')
    if s.get('minutes') not in limits['minutes']:
        err.append(f"{n}: minutes must be one of {limits['minutes']}, not {s.get('minutes')!r}")
        return err, warn
    unknown = [i for i in talks if i not in info]
    if unknown:
        err.append(f'{n}: talks not in this area: {unknown}')
        return err, warn
    cap = s['minutes'] // UNIT_MIN
    used = sum(info[i]['units'] for i in talks)
    if used > cap:
        err.append(f'{n}: {used} units in a {s["minutes"]}-minute session (holds {cap})')
    elif not limits['virtual'] and cap - used > MAX_EMPTY:
        err.append(f'{n}: {cap - used} empty units (at most {MAX_EMPTY}); change its length or move talks')
    elif limits['virtual'] and cap - used > 2:
        warn.append(f'{n}: {cap - used} empty units')
    inv = sum(info[i]['type'] == 'invited' for i in talks)
    if inv > MAX_INVITED:
        err.append(f'{n}: {inv} invited talks (at most {MAX_INVITED})')
    bad = [i for i in s.get('weakest_fits') or [] if i not in talks]
    if bad or len(s.get('weakest_fits') or []) > 3:
        err.append(f'{n}: weakest_fits must be up to 3 of the session\'s own talks')
    pos = {i: k for k, i in enumerate(talks)}
    series = collections.defaultdict(list)
    for i in talks:
        if info[i]['series']:
            series[info[i]['series']].append(i)
    for sid, ids in series.items():
        ks = sorted(pos[i] for i in ids)
        if ks != list(range(ks[0], ks[0] + len(ks))) or [info[talks[k]]['part'] for k in ks] != sorted(info[i]['part'] for i in ids):
            err.append(f'{n}: series {sid} must be consecutive and in part order')
    inst = collections.Counter(info[i]['institution'] for i in talks if info[i]['institution'])
    for name, c in inst.items():
        if c > limits['max_same_institution']:
            warn.append(f'{n}: {c} talks from {name} (soft limit {limits["max_same_institution"]})')
    if limits['virtual']:
        sets = [set(assumed.get(i, [])) or set(info[i]['windows']) for i in talks]
        sets = [x for x in sets if x]
        if sets and not set.intersection(*sets):
            err.append(f'{n}: its speakers share no time window')
        missing = [i for i in talks if not info[i]['windows'] and i not in assumed]
        if missing:
            err.append(f'{n}: no window for {missing}; add them to assumed_windows')
    return err, warn


def check_proposal(p, data):
    info, limits = data['talks'], data['limits']
    err, warn = [], []
    assumed = {i: windows(w) for i, w in (p.get('assumed_windows') or {}).items()}
    sessions = p.get('sessions') or []
    for k, s in enumerate(sessions, 1):
        e, w = session_problems(s, f'session {k}', info, limits, assumed)
        err += e; warn += w
    placed = [i for s in sessions for i in s.get('talks') or []]
    released = [r.get('id') for r in p.get('released') or []]
    for r in p.get('released') or []:
        if r.get('id') not in info:
            err.append(f"released: {r.get('id')!r} is not in this area")
        elif not str(r.get('reason', '')).strip() or not str(r.get('suggested_home', '')).strip():
            err.append(f"released {r['id']}: needs a reason and a suggested_home")
    count = collections.Counter(placed + released)
    dup = sorted((i for i, c in count.items() if c > 1), key=id_key)
    if dup:
        err.append(f'talks placed more than once: {dup}')
    missing = sorted((i for i in info if i not in count), key=id_key)
    if missing:
        err.append(f'talks neither placed nor released: {missing}')
    for sid in {info[i]['series'] for i in info if info[i]['series']}:
        homes = {('released' if i in released else next((k for k, s in enumerate(sessions) if i in s.get('talks', [])), None))
                 for i in info if info[i]['series'] == sid}
        if len(homes) > 1:
            err.append(f'series {sid} is split; keep all its parts together')
    if not limits['virtual']:
        lengths = collections.Counter(s.get('minutes') for s in sessions)
        if lengths[144] > limits['n144'] or lengths[108] > limits['n108']:
            err.append(f"{lengths[144]} x 144 and {lengths[108]} x 108 sessions; the share is at most "
                       f"{limits['n144']} x 144 and {limits['n108']} x 108")
    elif len(sessions) > limits['max_sessions']:
        err.append(f"{len(sessions)} sessions; at most {limits['max_sessions']}")
    total = sum(t['units'] for t in info.values())
    rel = sum(info[i]['units'] for i in released if i in info)
    if total and rel > RELEASE_WARN * total:
        warn.append(f'{rel} of {total} units released ({rel / total:.0%}); release only talks with no reasonable home here')
    for k, o in enumerate(p.get('options') or [], 1):
        rep = o.get('replaces') or []
        if not rep or any(not isinstance(x, int) or not 1 <= x <= len(sessions) for x in rep):
            err.append(f'option {k}: replaces must list session numbers 1-{len(sessions)}')
            continue
        old = sorted(i for x in rep for i in sessions[x - 1].get('talks', []))
        new_sessions = o.get('sessions') or []
        new = sorted(i for s in new_sessions for i in s.get('talks') or [])
        if old != new:
            err.append(f'option {k}: its sessions must hold exactly the talks of sessions {rep}')
        for j, s in enumerate(new_sessions, 1):
            e, w = session_problems(s, f'option {k} session {j}', info, limits, assumed)
            err += e; warn += w
        if not limits['virtual']:
            lengths = collections.Counter(s.get('minutes') for x, s in enumerate(sessions, 1) if x not in rep)
            lengths.update(s.get('minutes') for s in new_sessions)
            if lengths[144] > limits['n144'] or lengths[108] > limits['n108']:
                err.append(f'option {k}: would exceed the share of 144- or 108-minute sessions')
        if not str(o.get('why', '')).strip():
            err.append(f'option {k}: needs a why')
    return err, warn


def load_area(path):
    """(proposal, data) for work/sessions/AREA/proposal.json."""
    d = os.path.dirname(os.path.abspath(path))
    with open(os.path.join(d, 'talks.json'), encoding='utf-8') as f:
        data = json.load(f)
    with open(path, encoding='utf-8') as f:
        return json.load(f), data


def check(path):
    try:
        p, data = load_area(path)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f'ERROR {e}')
    err, warn = check_proposal(p, data)
    for e in err:
        print('ERROR', e)
    for w in warn:
        print('WARN', w)
    if not err:
        s = p.get('sessions') or []
        lengths = collections.Counter(x['minutes'] for x in s)
        print(f"OK {data['limits']['area']}: {len(s)} sessions ("
              + ', '.join(f'{n} x {m}' for m, n in sorted(lengths.items(), reverse=True))
              + f"), {len(p.get('released') or [])} talks released")
    return not err


# ---------- apply ----------
def kind(n_invited):
    return 'mini-symposium' if n_invited else 'contributed'


def estimates(data_dir, sessions, cfg):
    """{session_id: estimate dict with size and size_note}, or {} without the model or Ollama."""
    from dqi_sort import attendance
    try:
        model = attendance.load(data_dir)
        titles = [s['title'] for s in sessions]
        types = [s['kind'] for s in sessions]
        res = model.interest(titles, types, attendance.ollama_embed([attendance.session_text(t, y) for t, y in zip(titles, types)]))
    except Exception as e:           # no model file, or Ollama not running
        print(f'no attendance estimates ({e.__class__.__name__}: {e})')
        return {}
    sizes, sym_min = cfg.get('room_sizes'), cfg.get('symposium_min_seats', 0)
    out = {}
    for s, x in zip(sessions, res):
        if sizes:
            x['size'], x['size_note'] = model.size(x, s['kind'], sizes, sym_min)
        out[s['session_id']] = x
    return out


def room_budget(data_dir):
    """{size class: number of in-person slots in rooms of that class}."""
    rooms = {r['room_id']: r['size'] for r in read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    slots = read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))
    return collections.Counter(rooms.get(s['room_id'], '') for s in slots if s['track'] == 'in_person')


def apply(data_dir, replace=False, attendance=True):
    cfg = load_config(data_dir)
    talks = {t['talk_id']: t for t in read_csv(os.path.join(data_dir, 'talks.csv')) if t['status'] == 'active'}
    sort_dir = os.path.join(data_dir, 'sorting')
    if os.path.exists(os.path.join(sort_dir, 'assignments.csv')) and not replace:
        sys.exit('sorting/assignments.csv exists; pass --replace to overwrite the sort with these proposals')
    root = os.path.join(data_dir, 'work', 'sessions')
    areas = sorted(os.path.basename(d) for d in glob.glob(os.path.join(root, '*')) if os.path.isdir(d))
    props, failed = {}, []
    for area in areas:
        path = os.path.join(root, area, 'proposal.json')
        if not os.path.exists(path):
            failed.append(f'{area}: no proposal.json')
            continue
        p, data = load_area(path)
        err, _ = check_proposal(p, data)
        if err:
            failed.append(f'{area}: {len(err)} errors (run check)')
        props[area] = (p, data)
    if failed:
        sys.exit('not applied:\n' + '\n'.join(failed))
    sessions, assign, moves, options = [], {}, [], {}
    today = datetime.date.today().isoformat()
    for area, (p, data) in props.items():
        info = data['talks']

        def rows(ss, prefix, start=1):
            out = []
            for k, s in enumerate(ss, start):
                sid = f'{prefix}{k:02d}'
                inv = sum(info[i]['type'] == 'invited' for i in s['talks'])
                out.append({'session_id': sid, 'title': s['title'].strip(), 'kind': kind(inv), 'minutes': s['minutes'],
                            'size': '', 'area': area, 'locked': 'false', 'scope': s.get('scope', '').strip(), 'notes': '',
                            'talks': s['talks'], 'weakest_fits': s.get('weakest_fits') or [],
                            'used': sum(info[i]['units'] for i in s['talks']) * UNIT_MIN})
            return out
        mine = rows(p['sessions'], area)
        sessions += mine
        for s in mine:
            for k, i in enumerate(s['talks'], 1):
                assign[i] = {'talk_id': i, 'session_id': s['session_id'], 'order': k, 'locked': 'false', 'note': ''}
        for r in p.get('released') or []:
            note = f"released by {area}: {r['reason'].strip()} Suggested home: {r['suggested_home'].strip()}"
            assign[r['id']] = {'talk_id': r['id'], 'session_id': '', 'order': '', 'locked': 'false', 'note': note}
            moves.append({'when': today, 'commit': '', 'talk_id': r['id'], 'from': area, 'to': 'lonely', 'by': 'claude',
                          'reason': r['reason'].strip()})
        options[area] = [(o, rows(o['sessions'], f'{area}-O{k}-')) for k, o in enumerate(p.get('options') or [], 1)]
    for i in talks:
        assign.setdefault(i, {'talk_id': i, 'session_id': '', 'order': '', 'locked': 'false', 'note': 'in no proposal'})
    est = estimates(data_dir, sessions, cfg) if attendance else {}
    write_csv(os.path.join(sort_dir, 'sessions.csv'),
              ['session_id', 'title', 'kind', 'minutes', 'size', 'area', 'locked', 'scope', 'notes'], sessions)
    write_csv(os.path.join(sort_dir, 'assignments.csv'), ['talk_id', 'session_id', 'order', 'locked', 'note'],
              sorted(assign.values(), key=lambda r: id_key(r['talk_id'])))
    mpath = os.path.join(sort_dir, 'moves.csv')
    old = [m for m in read_csv(mpath) if not (m['by'] == 'claude' and m['to'] == 'lonely' and m['from'] in props)] \
        if os.path.exists(mpath) and not replace else []
    write_csv(mpath, ['when', 'commit', 'talk_id', 'from', 'to', 'by', 'reason'], old + moves)
    for area, opts in options.items():
        odir = os.path.join(sort_dir, 'options', area)
        for f in glob.glob(os.path.join(odir, '*.csv')):
            os.remove(f)
        for k, (o, ss) in enumerate(opts, 1):
            write_csv(os.path.join(odir, f'option{k}.csv'), ['session_id', 'title', 'minutes', 'order', 'talk_id', 'replaces', 'why'],
                      [{'session_id': s['session_id'], 'title': s['title'], 'minutes': s['minutes'], 'order': n, 'talk_id': i,
                        'replaces': ';'.join(f'{area}{x:02d}' for x in o['replaces']), 'why': o['why']}
                       for s in ss for n, i in enumerate(s['talks'], 1)])
    write_views(data_dir, cfg, talks, props, sessions, assign, options, est)
    lonely = sum(1 for r in assign.values() if not r['session_id'])
    print(f'{len(sessions)} sessions, {lonely} lonely talks; see views/sessions.md')


def write_views(data_dir, cfg, talks, props, sessions, assign, options, est):
    with open(os.path.join(data_dir, 'cards.jsonl'), encoding='utf-8') as f:
        cards = {c['talk_id']: c for c in map(json.loads, f) if c}
    vdir = os.path.join(data_dir, 'views', 'sessions')
    os.makedirs(vdir, exist_ok=True)
    for f in glob.glob(os.path.join(vdir, '*.md')):
        os.remove(f)
    n144, n108, slot_count, _ = grid(data_dir)
    budget = room_budget(data_dir)
    names = {a: v.get('name', '') for a, v in (cfg.get('areas') or {}).items()}

    def talk_line(i, weak=()):
        t, c = talks[i], cards.get(i) or {}
        mark = '**' if t['type'] == 'invited' else ''
        flag = ' (weak fit)' if i in weak else ''
        return f"| {i} | {mark}{t['title']}{mark}{flag} | {t['institution'] or t['affiliation']} | {c.get('key_claim', '')} |"

    def session_block(s):
        e = est.get(s['session_id'])
        att = f" · estimated peak {e['interest']} ({e['low']}–{e['high']}), suggested room {e['size']}" \
              + (f" ({e['size_note']})" if e.get('size_note') else '') if e else ''
        out = [f"### {s['session_id']}: {s['title']}", '',
               f"{s['minutes']} min, {s['used']} min filled · {s['kind']}{att}", '', f"_{s['scope']}_", '',
               '| ID | Title | Institution | Key claim |', '| --- | --- | --- | --- |']
        out += [talk_line(i, s['weakest_fits']) for i in s['talks']]
        return out + ['']

    summary = ['# Session proposals (stage 5)', '',
               'Generated by `dqi_sort.sessions apply`; do not edit. Per-area detail in `views/sessions/`.', '',
               '| Area | Talks | Sessions 144 / 108 (share) | Filled min / capacity | Released talks | Options |',
               '| --- | --- | --- | --- | --- | --- |']
    tot = collections.Counter()
    for area, (p, data) in props.items():
        mine = [s for s in sessions if s['area'] == area]
        L = collections.Counter(s['minutes'] for s in mine)
        lim = data['limits']
        share_txt = f"{lim['max_sessions']} virtual" if lim['virtual'] else f"{lim['n144']} / {lim['n108']}"
        cap = sum(s['minutes'] for s in mine)
        used = sum(s['used'] for s in mine)
        rel = len(p.get('released') or [])
        summary.append(f"| {area} | {len(data['talks'])} | {L[144]} / {L[108]}{' / ' + str(L[120]) + ' virtual' if L[120] else ''} "
                       f"({share_txt}) | {used} / {cap} | {rel} | {len(p.get('options') or [])} |")
        if not lim['virtual']:
            tot.update({'144': L[144], '108': L[108], 'used': used, 'cap': cap, 'rel': rel})
        block = [f"# {area}: {names.get(area, '')}", '', 'Generated by `dqi_sort.sessions apply`; do not edit.', '']
        if p.get('notes'):
            block += ['**Notes from the proposal:** ' + p['notes'].strip(), '']
        block += ['## Sessions', '']
        for s in mine:
            block += session_block(s)
        if p.get('released'):
            block += ['## Released to the lonely pool', '', '| ID | Title | Reason | Suggested home |', '| --- | --- | --- | --- |']
            block += [f"| {r['id']} | {talks[r['id']]['title']} | {r['reason']} | {r['suggested_home']} |" for r in p['released']]
            block.append('')
        for k, (o, ss) in enumerate(options.get(area) or [], 1):
            block += [f'## Option {k}: replaces ' + ', '.join(f'{area}{x:02d}' for x in o['replaces']), '', o['why'], '']
            for s in ss:
                block += session_block(s)
        with open(os.path.join(vdir, f'{area}.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(block).rstrip() + '\n')
    lonely = [r for r in assign.values() if not r['session_id']]
    summary += ['', f"In person: {tot['144']} x 144 and {tot['108']} x 108 sessions against {n144} x 144 and {n108} x 108 slots; "
                f"{tot['used']} of {tot['cap']} minutes filled; {len(lonely)} lonely talks "
                f"({sum(units(talks[r['talk_id']]) for r in lonely)} units) for packing, with "
                f"{n144 - tot['144']} x 144 and {n108 - tot['108']} x 108 slots left."]
    if est:
        want = collections.Counter(est[s['session_id']]['size'] for s in sessions if s['session_id'] in est and s['minutes'] != 120)
        summary += ['', 'Suggested room sizes (attendance model, each session on its own) against the rooms in the grid:', '',
                    '| Size | Suggested | Slots |', '| --- | --- | --- |']
        for c in sorted(cfg.get('room_sizes') or {}, key=lambda c: cfg['room_sizes'][c]):
            summary.append(f'| {c} | {want[c]} | {budget[c]} |')
    with open(os.path.join(data_dir, 'views', 'sessions.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['prepare', 'check', 'apply'])
    ap.add_argument('path', help='DATA_DIR, or for check the proposal.json')
    ap.add_argument('--replace', action='store_true', help='apply: overwrite an existing sort')
    ap.add_argument('--no-attendance', action='store_true', help='apply: skip the attendance estimates')
    a = ap.parse_args()
    if a.cmd == 'prepare':
        prepare(a.path)
    elif a.cmd == 'check':
        sys.exit(0 if check(a.path) else 1)
    else:
        apply(a.path, a.replace, not a.no_attendance)


if __name__ == '__main__':
    main()
