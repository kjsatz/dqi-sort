"""Stage 5: draft sessions per work area.

    python -m dqi_sort.sessions prepare DATA_DIR
    python -m dqi_sort.sessions check DATA_DIR/work/sessions/AREA/proposal.json

prepare  writes, per work area, work/sessions/AREA/: cards.txt (one compact card per talk, sorted by best category,
         with bridge talks marked "near OTHER" when most of their nearest neighbours are in other areas), brief.md
         (the area's numbers), prompt.md (prompts/session_spec.md, filled in) and talks.json (what `check` needs).
         One Claude agent per area then reads prompt.md and writes proposal.json there.
check    validates one draft: every talk placed once or released with a reason; in-person sessions of
         MIN_UNITS to MAX_UNITS units (length is chosen later, by the global pass: dqi_sort.pack); at most 2 invited
         talks; series together, consecutive and in order; virtual sessions of 120 minutes whose speakers share a
         time window. Prints ERROR and WARN lines, or OK.

Units: an oral talk is 1 unit (12 minutes), an invited talk 3. A 144-minute session holds 12 units, 108 holds 9.
"""
import argparse, collections, csv, glob, json, os, re, sys
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = os.path.join(HERE, 'prompts', 'session_spec.md')
UNIT_MIN = 12
MAX_INVITED = 2
MIN_UNITS, MAX_UNITS = 8, 12   # a draft session: 108 minutes one short, up to a full 144
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
def grid(data_dir):
    slots = read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))
    c = collections.Counter((s['track'], int(s['minutes'])) for s in slots)
    virtual = collections.Counter(s['start'] for s in slots if s['track'] == 'virtual')
    return c[('in_person', 144)], c[('in_person', 108)], c, virtual


# ---------- prepare ----------
def card_text(t, card, series_parts, near=None):
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
    if near:
        extra.append(near)
    if t['track'] == 'virtual':
        extra.append('windows: ' + (t['time_windows'] or 'none given'))
    if extra:
        lines.append('  ' + ' | '.join(extra))
    return '\n'.join(lines)


RULES_IN_PERSON = """- **Sizes.** An oral talk is 1 unit (12 minutes); an invited talk is 3 units (36 minutes). A draft session holds
  8 to 12 units. Do not choose its length: the global pass that follows makes each session 144 minutes
  (12 units, or 11) or 108 minutes (9 units, or 8), and trades a few talks between neighbouring sessions to fit
  the whole meeting's slots. Give each topic its natural size within that range. Across the area, sessions
  should average about {AVG} units (the meeting's average), so about {N} sessions for this area."""

RULES_VIRTUAL = """- **Lengths.** Every virtual session is 120 minutes: 10 units. An oral talk is 1 unit (12 minutes), an
  invited talk 3.
- **Time windows.** Each speaker lists the virtual time windows (Mountain Time) they can make. Every speaker in
  a session must share at least one window. For a speaker with no window listed, choose the window that suits
  their institution's location and record it in `assumed_windows` ({"id": "10:30-12:30"}), so the check uses it.
  Windows and how many virtual slots each has: {WINDOWS}.
- Give each session `"minutes": 120`. Use as few sessions as the windows allow (at most {NV}). Topic matters less than time here, but group by
  topic as far as the windows allow."""


def brief_text(area, spec, talks, limits):
    inv = sum(t['type'] == 'invited' for t in talks)
    u = sum(units(t) for t in talks)
    lines = [f"# {area}: {spec.get('name', '')}", '',
             f"{len(talks)} talks ({len(talks) - inv} oral, {inv} invited): {u} units."]
    if limits['virtual']:
        lines.append(f"Virtual track: at most {limits['max_sessions']} sessions of 120 minutes.")
    else:
        lines.append(f"Sessions of {MIN_UNITS} to {MAX_UNITS} units; about {limits['target_sessions']} sessions "
                     f"(the meeting averages {limits['avg_units']:.1f} units per session).")
        nb = sum(1 for t in talks if t.get('near'))
        lines.append(f"{nb} cards are marked as bridge talks (\"near ...\").")
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
    avg = (12 * n144 + 9 * n108) / max(1, n144 + n108)
    from dqi_sort.areas import neighbour_areas, bridge
    from dqi_sort.embed import load as load_embeddings
    ids, X, _ = load_embeddings(os.path.join(data_dir, 'embeddings', 'cards.npz'))
    near = bridge(neighbour_areas(ids, X, {t['talk_id']: t['area'] for t in talks if t['track'] == 'in_person'}))
    for t in talks:
        t['near'] = near.get(t['talk_id'])
    series_parts = collections.Counter(t['series'] for t in talks if t['series'])
    root = os.path.join(data_dir, 'work', 'sessions')
    if glob.glob(os.path.join(root, '*', 'proposal.json')):
        sys.exit(f'proposals already exist in {root}; start the global pass from them, or move them away to start again')
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
            target = round(sum(units(t) for t in ts) / avg)
            limits = {'virtual': False, 'target_sessions': target, 'avg_units': avg}
            rules = RULES_IN_PERSON.replace('{AVG}', f'{avg:.1f}').replace('{N}', str(target))
        limits.update(area=area, max_same_institution=max_inst)
        info = {t['talk_id']: {'type': t['type'], 'units': units(t), 'series': t['series'],
                               'part': int(t['series_part'] or 0), 'institution': t['institution'] or t['affiliation'],
                               'windows': sorted(windows(t['time_windows']))} for t in ts}
        with open(os.path.join(d, 'talks.json'), 'w', encoding='utf-8') as f:
            json.dump({'limits': limits, 'talks': info}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(d, 'cards.txt'), 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(card_text(t, cards.get(t['talk_id']), series_parts, t['near']) for t in ts) + '\n')
        with open(os.path.join(d, 'brief.md'), 'w', encoding='utf-8') as f:
            f.write(brief_text(area, (cfg.get('areas') or {}).get(area, {}), ts, limits))
        check_cmd = f"cd {HERE} && .venv/bin/python -m dqi_sort.sessions check {os.path.abspath(d)}/proposal.json"
        with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
            f.write(spec_text.replace('{RULES}', rules).replace('{MAX_INST}', str(max_inst))
                    .replace('{CHECK}', check_cmd).replace('{DIR}', os.path.abspath(d)))
        cap = f"{limits['max_sessions']} virtual" if limits['virtual'] else f"~{limits['target_sessions']} sessions"
        print(f"{area:8s} {len(ts):4d} talks {sum(units(t) for t in ts):5d} units   {cap}   {sum(1 for t in ts if t['near'])} bridge")
    print(f'grid: {n144} x 144 + {n108} x 108 in person ({12 * n144 + 9 * n108} units); files in {root}')


# ---------- check ----------
def session_problems(s, n, info, limits, assumed):
    """Errors and warnings for one session dict; n is its label."""
    err, warn = [], []
    talks = s.get('talks') or []
    if not str(s.get('title', '')).strip():
        err.append(f'{n}: no title')
    if limits['virtual'] and s.get('minutes') not in limits['minutes']:
        err.append(f"{n}: minutes must be one of {limits['minutes']}, not {s.get('minutes')!r}")
        return err, warn
    unknown = [i for i in talks if i not in info]
    if unknown:
        err.append(f'{n}: talks not in this area: {unknown}')
        return err, warn
    used = sum(info[i]['units'] for i in talks)
    if limits['virtual']:
        cap = s['minutes'] // UNIT_MIN
        if used > cap:
            err.append(f'{n}: {used} units in a {s["minutes"]}-minute session (holds {cap})')
        elif cap - used > 2:
            warn.append(f'{n}: {cap - used} empty units')
    elif not MIN_UNITS <= used <= MAX_UNITS:
        err.append(f'{n}: {used} units; a draft session holds {MIN_UNITS} to {MAX_UNITS}')
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
    if limits['virtual'] and len(sessions) > limits['max_sessions']:
        err.append(f"{len(sessions)} sessions; at most {limits['max_sessions']}")
    total = sum(t['units'] for t in info.values())
    rel = sum(info[i]['units'] for i in released if i in info)
    if total and rel > RELEASE_WARN * total:
        warn.append(f'{rel} of {total} units released ({rel / total:.0%}); release only talks with no reasonable home here')
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
        sizes = collections.Counter(sum(data['talks'][i]['units'] for i in x['talks']) for x in s)
        print(f"OK {data['limits']['area']}: {len(s)} sessions (units: "
              + ', '.join(f'{u}: {n}' for u, n in sorted(sizes.items())) + f"), {len(p.get('released') or [])} talks released")
    return not err


# ---------- shared with the global pass ----------
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
    cutoffs, seats, sym_min = cfg.get('size_cutoffs'), cfg.get('room_sizes'), cfg.get('symposium_min_seats', 0)
    out = {}
    for s, x in zip(sessions, res):
        if cutoffs:
            x['size'], x['size_note'] = model.size(x, s['kind'], cutoffs, seats, sym_min)
        out[s['session_id']] = x
    return out


def room_budget(data_dir):
    """{size class: number of in-person slots in rooms of that class}."""
    rooms = {r['room_id']: r['size'] for r in read_csv(os.path.join(data_dir, 'venue', 'rooms.csv'))}
    slots = read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))
    return collections.Counter(rooms.get(s['room_id'], '') for s in slots if s['track'] == 'in_person')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['prepare', 'check'])
    ap.add_argument('path', help='DATA_DIR, or for check the proposal.json')
    a = ap.parse_args()
    if a.cmd == 'prepare':
        prepare(a.path)
    else:
        sys.exit(0 if check(a.path) else 1)


if __name__ == '__main__':
    main()
