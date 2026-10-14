"""Stage 10: session chairs. Link volunteers to abstracts, group sessions into recruiting topics, write the
coordinator's handoff sheet.

    python -m dqi_sort.chairs topics-prepare DATA_DIR
    python -m dqi_sort.chairs topics-check   DATA_DIR
    python -m dqi_sort.chairs handoff        DATA_DIR

topics-prepare  writes work/chairs/sessions.md (every in-person session: ID, area, title, scope) and prompt.md
                (prompts/chair_topics_spec.md). One Claude agent groups the sessions into recruiting topics and writes
                work/chairs/topics.json; topics-check validates it (every session in exactly one topic).
handoff         reads the APS volunteer lists (config.yaml `chair_volunteers`: in_person and virtual files), keeps
                the rows whose sub-category starts with the division code, merges people by email, and links each to
                their abstracts: the row's abstract ID, plus any other talk by the same name (flagged for the lead).
                Writes chairs/topics.csv (topic, area, sessions, when they run, chairs needed: one per in-person
                session, two per virtual session, no backups; the virtual conference is one topic) and chairs/volunteers.csv,
                and the handoff Google Sheet in the review folder: Topics, Volunteers (with empty return columns
                status, topics, unavailable, note, the only cells the coordinator edits) and How to fill in.
                Suggested topic: the topic of the volunteer's own session, or Virtual for virtual chairs.
"""
import argparse, collections, json, os, re, sys
from dqi_sort import sessions as S

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
VIRTUAL = 'Virtual conference'
RETURN_COLS = ['Status', 'Topics', 'Unavailable', 'Note']
HOW = [['Column', 'What to enter'],
       ['Status', 'confirmed, declined or no reply'],
       ['Topics', 'One or more topics from the Topics tab, exactly as written there, separated by ;'],
       ['Unavailable', 'Days or half-days they cannot chair, e.g. Mon AM; Thu. Leave blank if none.'],
       ['Note', 'Anything else, in free text'],
       ['', ''],
       ['Notes', 'Offer a topic, not a session: sessions are matched to confirmed chairs later, never against their own talks or '
                 'stated unavailability. In-person sessions get chairs who present in person; the virtual conference needs '
                 'two confirmed chairs per session, preferably virtual presenters. Only the four return columns can be edited.']]


def col(row, *names):
    for k in row:
        low = re.sub(r'\s+', ' ', k).strip().lower()
        if any(low.startswith(n) for n in names):
            return (row[k] or '').strip()
    return ''


def norm(name):
    return re.sub(r'[^a-z]', '', name.lower())


# ---------- topics ----------
def topics_prepare(data_dir):
    sess = [s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv')) if s['area'] != 'VIRTUAL']
    d = os.path.join(data_dir, 'work', 'chairs')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'sessions.md'), 'w', encoding='utf-8') as f:
        f.write(f'# In-person sessions ({len(sess)})\n\n' + '\n'.join(f"- {s['session_id']} [{s['area']}] {s['title']}: {s['scope']}" for s in sess) + '\n')
    with open(os.path.join(S.HERE, 'prompts', 'chair_topics_spec.md'), encoding='utf-8') as f:
        spec = f.read()
    check = f'cd {S.HERE} && .venv/bin/python -m dqi_sort.chairs topics-check {os.path.abspath(data_dir)}'
    with open(os.path.join(d, 'prompt.md'), 'w', encoding='utf-8') as f:
        f.write(spec.replace('{DIR}', os.path.abspath(d)).replace('{CHECK}', check))
    print(f'{len(sess)} sessions -> {d}')


def topics_check(data_dir):
    sess = {s['session_id'] for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv')) if s['area'] != 'VIRTUAL'}
    with open(os.path.join(data_dir, 'work', 'chairs', 'topics.json'), encoding='utf-8') as f:
        topics = json.load(f)
    seen = collections.Counter(x for t in topics for x in t['sessions'])
    errs = [f'{x} is in {n} topics' for x, n in seen.items() if n > 1] + [f'{x} is in no topic' for x in sorted(sess - set(seen))]
    errs += [f'{x} is not an in-person session' for x in seen if x not in sess]
    errs += [f"topic {t['topic']!r} has {len(t['sessions'])} sessions" for t in topics if not 2 <= len(t['sessions']) <= 10]
    names = collections.Counter(t['topic'] for t in topics)
    errs += [f'topic name {n!r} is used twice' for n, c in names.items() if c > 1]
    for e in errs:
        print('ERROR', e)
    print('OK' if not errs else f'{len(errs)} errors', f'({len(topics)} topics)')
    return errs


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


def handoff(data_dir):
    cfg = S.load_config(data_dir)
    talks = {t['talk_id']: t for t in S.read_csv(os.path.join(data_dir, 'talks.csv'))}
    sess = {s['session_id']: s for s in S.read_csv(os.path.join(data_dir, 'sorting', 'sessions.csv'))}
    assign = {a['talk_id']: a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))}
    slots = {s['slot_id']: s for s in S.read_csv(os.path.join(data_dir, 'schedule', 'slots.csv'))}
    sched = {r['session_id']: slots[r['slot_id']] for r in S.read_csv(os.path.join(data_dir, 'schedule', 'schedule.csv'))}
    if topics_check(data_dir):
        sys.exit('fix work/chairs/topics.json first')
    with open(os.path.join(data_dir, 'work', 'chairs', 'topics.json'), encoding='utf-8') as f:
        topics = json.load(f)
    virtual = sorted(s for s in sess if sess[s]['area'] == 'VIRTUAL')
    topics.append({'topic': VIRTUAL, 'area': 'VIRTUAL', 'sessions': virtual})
    topic_of = {x: t['topic'] for t in topics for x in t['sessions']}
    when = lambda x: f"{sched[x]['day']} {sched[x]['start']}" if x in sched else ''
    trows = []
    for t in topics:
        n = len(t['sessions'])
        need = 2 * n if t['area'] == 'VIRTUAL' else n          # one confirmed chair per session, two per virtual session; no backups
        days = sorted({sched[x]['day'] for x in t['sessions'] if x in sched}, key=DAYS.index)
        trows.append({'topic': t['topic'], 'area': t['area'], 'sessions': ';'.join(t['sessions']), 'n_sessions': n, 'chairs_needed': need,
                      'days': ' '.join(days), 'titles': '; '.join(f"{x} {sess[x]['title']} ({when(x)})" for x in t['sessions'])})
    vols = volunteers(data_dir, cfg, talks)
    for v in vols:
        own = [assign.get(i, '') for i in v['talk_ids'].split(';') if i]
        tops = [topic_of[x] for x in own if x in topic_of]
        v['suggested_topic'] = VIRTUAL if v['chair_mode'] == 'virtual' or 'virtual' in v['presenting_mode'] else (tops[0] if tops else '')
        v['own_sessions'] = ';'.join(f"{x} ({when(x)})" for x in own if x)
    os.makedirs(os.path.join(data_dir, 'chairs'), exist_ok=True)
    S.write_csv(os.path.join(data_dir, 'chairs', 'topics.csv'), ['topic', 'area', 'sessions', 'n_sessions', 'chairs_needed', 'days', 'titles'], trows)
    S.write_csv(os.path.join(data_dir, 'chairs', 'volunteers.csv'),
                ['volunteer_id', 'name', 'email', 'affiliation', 'chair_mode', 'presenting_mode', 'chaired_before', 'talk_ids',
                 'own_sessions', 'suggested_topic', 'match_note'], vols)
    sheet(data_dir, cfg, trows, vols, talks)
    supply = collections.Counter(v['suggested_topic'] for v in vols)
    print(f"{len(vols)} volunteers ({sum(v['chair_mode'] != 'in_person' for v in vols)} can chair virtually); {len(trows)} topics needing "
          f"{sum(t['chairs_needed'] for t in trows)} chairs; topics with fewer suggested volunteers than chairs needed: "
          f"{sum(1 for t in trows if supply[t['topic']] < t['chairs_needed'])}")


def sheet(data_dir, cfg, trows, vols, talks):
    from dqi_sort import gsheets
    from dqi_sort.sheets import Book, tab_requests, protect_req, HEADER_ROW, LOG_COLS
    folder = (cfg.get('sheets') or {}).get('folder_id')
    name = (cfg.get('sheets') or {}).get('folder_name', 'DQI')
    b = Book(f'{name}: session chair handoff for the coordinator. Edit only the four return columns of the Volunteers tab.')
    b.tab('Topics', ['Topic', 'Area', 'Sessions', 'Chairs needed', 'Days', 'Sessions and times'],
          [[t['topic'], t['area'], t['n_sessions'], t['chairs_needed'], t['days'], t['titles'].replace('; ', '\n')] for t in trows],
          lambda sid, n: tab_requests(sid, n, [240, 80, 70, 90, 140, 560], wrap_cols=[0, 5]) + protect_req(sid))
    vr = []
    for v in sorted(vols, key=lambda v: (v['suggested_topic'] or 'zzz', v['name'])):
        titles = '\n'.join(f"{i}: {talks[i]['title']}" for i in v['talk_ids'].split(';') if i in talks)
        vr.append([v['volunteer_id'], v['name'], v['email'], v['affiliation'], v['chair_mode'].replace('_', '-'),
                   v['presenting_mode'].replace('_', '-'), v['chaired_before'], titles, v['own_sessions'].replace(';', '\n'),
                   v['suggested_topic'], v['match_note'], '', '', '', ''])
    header = ['ID', 'Name', 'Email', 'Affiliation', 'Can chair', 'Presenting', 'Chaired before', 'Their abstracts', 'Their sessions',
              'Suggested topic', 'Match note'] + RETURN_COLS
    editable = list(range(len(header) - 4, len(header)))
    b.tab('Volunteers', header, vr, lambda sid, n: tab_requests(sid, n, [60, 160, 200, 200, 80, 80, 70, 330, 150, 200, 200, 100, 200, 140, 220],
                                                                   wrap_cols=[3, 7, 8, 9, 10, 12, 14], notes_cols=editable)
          + protect_req(sid, n, editable))
    b.tab('How to fill in', HOW[0], HOW[1:], lambda sid, n: tab_requests(sid, n, [140, 700], wrap_cols=[1]) + protect_req(sid))
    drive, sheets = gsheets.services()
    log_path = os.path.join(data_dir, 'sorting', 'sheets.csv')
    log = S.read_csv(log_path) if os.path.exists(log_path) else []
    row = next((r for r in reversed(log) if r['kind'] == 'chairs'), None)
    fresh = row is None
    sid = gsheets.create_sheet(drive, f'{name}: session chair handoff', folder) if fresh else row['sheet_id']
    b.write(sheets, sid, fresh)
    commit = __import__('subprocess').run(['git', '-C', data_dir, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    now = __import__('datetime').datetime.now().isoformat(timespec='minutes')
    if fresh:
        log.append({'kind': 'chairs', 'area': '', 'round': '', 'commit': commit, 'content': '', 'sheet_id': sid, 'url': gsheets.url(sid), 'made': now})
    else:
        row.update(commit=commit, made=now)
    S.write_csv(log_path, LOG_COLS, log)
    print('chair handoff:', gsheets.url(sid))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['topics-prepare', 'topics-check', 'handoff'])
    ap.add_argument('data_dir')
    a = ap.parse_args()
    if a.cmd == 'topics-prepare':
        topics_prepare(a.data_dir)
    elif a.cmd == 'topics-check':
        sys.exit(1 if topics_check(a.data_dir) else 0)
    else:
        handoff(a.data_dir)


if __name__ == '__main__':
    main()
