"""Stage 11, late changes: add a talk, withdraw talks, move a talk, each a small local edit that is checked at once.

    python -m dqi_sort.late add      DATA_DIR TALK [--to SESSION [--position N]] [--note TEXT]
                                     [--title T --speaker S --affiliation A --type oral|invited --track in_person|virtual
                                      --category CODE --abstract FILE --submitter-notes TEXT]
    python -m dqi_sort.late withdraw DATA_DIR TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.late move     DATA_DIR TALK SESSION|lonely --reason TEXT [--position N] [--force]

add       a late submission. If the talk is already in talks.csv (intake on an APS export that has it), it only
          enters the sort; otherwise give its fields and it is added to talks.csv (flagged late_add) and
          abstracts.jsonl. It goes into the lonely pool, or into SESSION at position N (end by default). Logged as a
          late addition in sorting/status_log.csv, so the reconciliation with APS's list accounts for it. A talk
          brought in from another unit goes through `python -m dqi_sort.decide received UNIT TALK` instead.
          Then build its card and embedding (cards prepare, which picks up talks with no card; embed) so `review homes` can suggest a home.
withdraw  the speaker withdrew: status withdrawn (`decide withdraw`), out of its session.
move      one talk to another session (or the pool), at position N (end by default). Refuses to overfill a
          session or cross the in-person/virtual partition (--force allows overfilling, to make room after).

Every change is committed to the data repo and followed by the validator: the problems it finds in the sessions
touched (a session short or over its length, an invited talk no longer on its block, a series split, a speaker or
chair clash in the schedule) are printed, so the lead can approve the change or fix the gap (move a talk in from the
pool, or re-order with `order`).
"""
import argparse, datetime, json, os, subprocess, sys
from dqi_sort import decide as D, review as R, sessions as S, validate as V


def commit(data_dir, message):
    if subprocess.run(['git', '-C', data_dir, 'rev-parse'], capture_output=True).returncode:
        return
    paths = [p for p in ('talks.csv', 'abstracts.jsonl', 'sorting', 'views/flags.md') if os.path.exists(os.path.join(data_dir, p))]
    subprocess.run(['git', '-C', data_dir, 'add', '--', *paths], check=True)
    r = subprocess.run(['git', '-C', data_dir, 'commit', '-q', '-m', message, '--', *paths], capture_output=True, text=True)
    print('committed to the data repo' if r.returncode == 0 else 'nothing to commit')


def report(data_dir, touched):
    """Validator problems that name a touched session or talk; a count of the rest."""
    probs, _ = V.validate(data_dir, quiet=True)
    touched = {x for x in touched if x}
    mine = [(l, t) for l, t in probs if any(x in t.replace(',', ' ').replace(':', ' ').split() for x in touched)]
    for l, t in mine:
        print(l, t)
    rest = [p for p in probs if p not in mine and p[0] == 'ERROR']
    print(f"check: {len(mine)} problems in what changed" + (f'; {len(rest)} errors elsewhere (python -m dqi_sort.validate)' if rest else ''))
    return mine


def add(data_dir, talk, to='', position=None, note='', fields=None, do_commit=True):
    tpath = os.path.join(data_dir, 'talks.csv')
    rows = S.read_csv(tpath)
    cols = list(rows[0])
    talks = {r['talk_id']: r for r in rows}
    apath = os.path.join(data_dir, 'sorting', 'assignments.csv')
    assign = {a['talk_id']: a for a in S.read_csv(apath)}
    if talk in assign:
        sys.exit(f'{talk} is already in the sort (session {assign[talk]["session_id"] or "lonely"}); use move')
    fields = {k: v for k, v in (fields or {}).items() if v}
    if talk not in talks:
        need = [k for k in ('title', 'speaker', 'type', 'track') if not fields.get(k)]
        if need:
            sys.exit(f"{talk} is not in talks.csv: give --{' --'.join(need)} (or run intake on an APS export that has it)")
        cfg = S.load_config(data_dir)
        minutes = (cfg.get('talk_lengths_min') or {'oral': 12, 'invited': 36})[fields['type']]
        talks[talk] = {c: '' for c in cols}
        talks[talk].update(talk_id=talk, track=fields['track'], type=fields['type'], minutes=str(minutes), title=fields['title'],
                           speaker=fields['speaker'], affiliation=fields.get('affiliation', ''), institution=fields.get('affiliation', ''),
                           submitted_category=fields.get('category', ''), status='active', flags='late_add')
        rows.append(talks[talk])
        rows.sort(key=lambda r: S.id_key(r['talk_id']))
        S.write_csv(tpath, cols, rows)
        body = open(fields['abstract'], encoding='utf-8').read().strip() if fields.get('abstract') else ''
        jpath = os.path.join(data_dir, 'abstracts.jsonl')
        recs = []
        if os.path.exists(jpath):
            with open(jpath, encoding='utf-8') as f:
                recs = [json.loads(x) for x in f if x.strip()]
        recs.append({'talk_id': talk, 'title': fields['title'], 'body': body, 'submitter_notes': fields.get('submitter_notes', '')})
        recs.sort(key=lambda r: S.id_key(r['talk_id']))
        with open(jpath, 'w', encoding='utf-8') as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + '\n' for r in recs)
    t = talks[talk]
    if t['status'] != 'active':
        sys.exit(f"{talk} has status {t['status']}; use decide reinstate")
    now = datetime.datetime.now().isoformat(timespec='minutes')
    assign[talk] = {'talk_id': talk, 'session_id': '', 'order': '', 'locked': 'false', 'note': f'late addition ({now[:10]})'}
    S.write_csv(apath, ['talk_id', 'session_id', 'order', 'locked', 'note'], sorted(assign.values(), key=lambda a: S.id_key(a['talk_id'])))
    sdir = os.path.join(data_dir, 'sorting')
    D.append_csv(os.path.join(sdir, 'status_log.csv'), D.LOG_COLS,
                 [{'when': now, 'talk_id': talk, 'from_status': 'new', 'to_status': 'active', 'unit': '', 'by': 'lead', 'note': note or 'late addition'}])
    D.append_csv(os.path.join(sdir, 'moves.csv'), D.MOVE_COLS,
                 [{'when': now[:10], 'commit': '', 'talk_id': talk, 'from': 'new', 'to': 'lonely', 'by': 'lead', 'reason': note or 'late addition'}])
    print(f'{talk}: late addition, in the lonely pool')
    if to:
        R.move_one(data_dir, talk, to, note or 'late addition', by='lead', position=position)
    if do_commit:
        commit(data_dir, f"late add: {talk}" + (f' into {to}' if to else ' (lonely)') + (f' ({note})' if note else ''))
    print(f'next: its card and embedding (python -m dqi_sort.cards prepare {data_dir} makes batches for talks with no card; then embed)')
    return report(data_dir, {talk, to})


def withdraw(data_dir, ids, note='', do_commit=True):
    where = {a['talk_id']: a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv'))}
    D.decide(data_dir, 'withdraw', ids, note=note, do_commit=False)
    if do_commit:
        commit(data_dir, f"late withdraw: {', '.join(ids)}" + (f' ({note})' if note else ''))
    return report(data_dir, set(ids) | {where.get(i, '') for i in ids})


def move(data_dir, talk, to, reason, position=None, force=False, do_commit=True):
    frm = next((a['session_id'] for a in S.read_csv(os.path.join(data_dir, 'sorting', 'assignments.csv')) if a['talk_id'] == talk), '')
    R.move_one(data_dir, talk, to, reason, by='lead', position=position, force=force)
    if do_commit:
        commit(data_dir, f"late move: {talk} {frm or 'lonely'} -> {to} ({reason})")
    return report(data_dir, {talk, frm, '' if to == 'lonely' else to})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['add', 'withdraw', 'move'])
    ap.add_argument('data_dir')
    ap.add_argument('args', nargs='+', help='add: TALK; withdraw: TALK [TALK ...]; move: TALK SESSION|lonely')
    ap.add_argument('--to', default='')
    ap.add_argument('--position', type=int)
    ap.add_argument('--note', default='')
    ap.add_argument('--reason', default='')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-commit', action='store_true')
    for f in ('title', 'speaker', 'affiliation', 'category', 'abstract', 'submitter-notes'):
        ap.add_argument(f'--{f}', default='')
    ap.add_argument('--type', choices=['oral', 'invited'])
    ap.add_argument('--track', choices=['in_person', 'virtual'])
    a = ap.parse_args()
    c = not a.no_commit
    if a.cmd == 'add':
        fields = {k: getattr(a, k) for k in ('title', 'speaker', 'affiliation', 'category', 'abstract', 'submitter_notes', 'type', 'track')}
        add(a.data_dir, a.args[0], a.to, a.position, a.note, fields, c)
    elif a.cmd == 'withdraw':
        withdraw(a.data_dir, a.args, a.note, c)
    else:
        if len(a.args) != 2 or not a.reason:
            sys.exit('move needs TALK SESSION|lonely and --reason')
        move(a.data_dir, a.args[0], a.args[1], a.reason, a.position, a.force, c)


if __name__ == '__main__':
    main()
