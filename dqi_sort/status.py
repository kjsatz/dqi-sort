"""Where the run stands: each stage of PROCESS.md, done or not, and the next step.

    python -m dqi_sort.status DATA_DIR

Reads only the data folder (no network, no Ollama) and prints one line per stage with what the files show, then
what waits on the lead (unticked open questions, review rounds out) and the next command to run (RUNBOOK.md has the
whole sequence). A new lead, or Claude starting a fresh session, runs this first.
"""
import argparse, collections, json, os, re, sys
from dqi_sort import sessions as S, validate as V

DONE, TODO, PART = 'done', 'to do', 'partly'


def count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8') as f:
        return sum(1 for line in f if line.strip())


def stages(data_dir):
    """[(stage, state, detail, next command)] from the files in the data folder."""
    p = lambda *x: os.path.join(data_dir, *x)
    out = []
    try:
        cfg = S.load_config(data_dir)
    except FileNotFoundError:
        return [('0. Prepare', TODO, 'no config.yaml', 'python -m dqi_sort.new_year (see RUNBOOK.md)')]
    d = V.load(data_dir)
    talks, sess, members, sched = d['talks'], d['sess'], d['members'], d['sched']
    active = {i: t for i, t in talks.items() if t['status'] == 'active'}
    inp = [i for i in ('in_person', 'virtual') if os.path.exists(p(((cfg.get('aps_input') or {}).get(i) or {}).get('file', f'input/{i}.csv')))]

    todo_cfg = [k for k in ('meeting_dates', 'division_code', 'dqi_categories', 'areas') if not cfg.get(k)]
    if not (cfg.get('aps_sheet') or {}).get('id'):
        todo_cfg.append('aps_sheet.id')
    rooms = V.read(data_dir, 'venue', 'rooms.csv')
    slots = [s for s in d['slots'].values() if s.get('track') == 'in_person']
    prep = [f'config missing: {", ".join(todo_cfg)}' if todo_cfg else 'config set',
            f'{len(rooms)} rooms, {len(slots)} in-person slots' if rooms else 'no venue/rooms.csv yet',
            'attendance model ready' if os.path.exists(p('history', 'attendance_model.npz')) else 'no history/attendance_model.npz']
    out.append(('0. Prepare', DONE if not todo_cfg and rooms else PART, '; '.join(prep), 'python -m dqi_sort.aps_input check DATA'))

    out.append(('1. Intake', DONE if talks else TODO,
                f"{len(talks)} talks ({len(active)} active) from {', '.join(inp) or 'no input yet'}" if talks else 'no talks.csv',
                'python -m dqi_sort.aps_input pull DATA; python -m dqi_sort.intake DATA'))

    cards = set()
    if os.path.exists(p('cards.jsonl')):
        with open(p('cards.jsonl'), encoding='utf-8') as f:
            cards = {json.loads(l)['talk_id'] for l in f if l.strip()}
    miss = sorted(set(active) - cards, key=S.id_key)
    emb = os.path.exists(p('embeddings', 'cards.npz'))
    out.append(('2. Cards', TODO if not cards else (DONE if not miss and emb else PART),
                f'{len(cards)} cards; {len(miss)} active talks without one' + (f" ({', '.join(miss[:5])}{'...' if len(miss) > 5 else ''})" if miss else '')
                + ('' if emb else '; no embeddings'),
                'python -m dqi_sort.cards prepare DATA --ids FILE (then Haiku agents, cards merge, embed)'))

    series = {t['series'] for t in active.values() if t.get('series')}
    out.append(('3. Linking', DONE if series or os.path.isdir(p('work', 'linking')) else TODO, f'{len(series)} series', 'python -m dqi_sort.linking ...'))
    with_area = sum(1 for t in active.values() if t.get('area'))
    out.append(('4. Areas and flags', DONE if with_area == len(active) and active else (PART if with_area else TODO),
                f'{with_area} of {len(active)} active talks have an area', 'python -m dqi_sort.areas DATA'))

    placed = {t for m in members.values() for t in m}
    lonely = [i for i in active if i not in placed]
    out.append(('5-6. Sessions', DONE if sess and not lonely else (PART if sess else TODO),
                f'{len(sess)} sessions; {len(lonely)} active talks in no session', 'python -m dqi_sort.pack ... (docs/sessions.md)'))

    chk = p('views', 'aps_sheet_check.md')
    txt = open(chk, encoding='utf-8').read() if os.path.exists(chk) else ''
    ok = 'Matches the sort in git' in txt                # delivered: rounds still out are closed
    rounds = V.read(data_dir, 'sorting', 'sheets.csv')
    applied = {(r.get('area'), str(r.get('round'))) for r in V.read(data_dir, 'sorting', 'reviews.csv')}
    latest = {}
    for r in rounds:
        if r.get('kind') == 'area':
            latest[r['area']] = max(latest.get(r['area'], 0), int(r['round'] or 0))
    out_now = sorted(a for a, n in latest.items() if (a, str(n)) not in applied)
    out.append(('7. Review', (PART if out_now and not ok else DONE) if latest else TODO,
                f"{len(latest)} areas sent; latest round not applied: {', '.join(out_now) or 'none'} (read back; apply if changed)",
                'python -m dqi_sort.review read DATA AREA (then apply)'))

    ip = [s for s in sess if not V.is_virtual(sess[s])]
    placed_s = [s for s in sess if s in sched]
    out.append(('8. Schedule', DONE if sess and len(placed_s) == len(sess) else (PART if placed_s else TODO),
                f'{len(placed_s)} of {len(sess)} sessions in a slot', 'python -m dqi_sort.schedule budget/solve DATA'))

    blocks = [r for r in rooms if r.get('invited_block_144') or r.get('invited_block_108')]
    order_errs = [m for lvl, m in V.check_sessions(d, True) if lvl == 'ERROR' and 'invited talk' in m]
    out.append(('9. Talk order', DONE if blocks and not order_errs else (PART if blocks else TODO),
                f'{len(blocks)} rooms with an invited-talk block' + (f'; {len(order_errs)} order problems' if order_errs else ''),
                'python -m dqi_sort.order positions/prepare/apply DATA'))

    have = collections.Counter(x for c in d['chairs'] for x in V.chair_codes(c))
    need = sum(2 if V.is_virtual(sess[s]) else 1 for s in sess)
    got = sum(min(have[s], 2 if V.is_virtual(sess[s]) else 1) for s in sess)
    out.append(('10. Chairs', DONE if sess and got == need else (PART if got else TODO), f'{got} of {need} chairs', 'python -m dqi_sort.chairs sync DATA'))

    out.append(('11. Deliver', DONE if ok else (PART if txt else TODO),
                (txt.splitlines()[0].lstrip('# ') + (': matches' if ok else ': mismatches')) if txt else "APS's sheet not filled yet",
                'python -m dqi_sort.aps_fill write DATA; aps_fill check DATA'))
    return out


def waiting(data_dir):
    """What waits on the lead: unticked open questions, and the last checkpoint heading."""
    out = []
    oq = os.path.join(data_dir, 'open_questions.md')
    if os.path.exists(oq):
        with open(oq, encoding='utf-8') as f:
            txt = f.read()
        open_items = re.findall(r'^- \[ \] \*\*(.+?)\*\*', txt, re.M)
        out.append(f"{len(open_items)} open questions (open_questions.md)" + (f": {'; '.join(open_items[:6])}" if open_items else ''))
    cp = os.path.join(data_dir, 'checkpoints.md')
    if os.path.exists(cp):
        with open(cp, encoding='utf-8') as f:
            heads = re.findall(r'^## (.+)$', f.read(), re.M)
        if heads:
            out.append(f'last checkpoint: {heads[-1]}')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    a = ap.parse_args()
    rows = stages(a.data_dir)
    w = max(len(r[0]) for r in rows)
    for stage, state, detail, _ in rows:
        print(f'{stage:<{w}}  {state:<7} {detail}')
    probs, _ = V.validate(a.data_dir, delivery=any(r[0].startswith('11') and r[1] != TODO for r in rows), quiet=True)
    n = collections.Counter(l for l, _ in probs)
    print(f"\nValidator: {n['ERROR']} errors, {n['WARN']} warnings (python -m dqi_sort.validate {a.data_dir})")
    for line in waiting(a.data_dir):
        print(line)
    nxt = next((r for r in rows if r[1] != DONE), None)
    print(f"\nNext: {nxt[0]}: {nxt[3].replace('DATA', a.data_dir)}  (RUNBOOK.md)" if nxt else '\nAll stages done. Late changes: python -m dqi_sort.late (RUNBOOK.md)')


if __name__ == '__main__':
    main()
