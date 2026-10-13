"""The lead's decisions on a talk's status, with a dated record of each (sorting/status_log.csv).

    python -m dqi_sort.decide offer     DATA_DIR UNIT TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide exchanged DATA_DIR TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide returned  DATA_DIR TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide received  DATA_DIR UNIT TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide poster    DATA_DIR TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide keep      DATA_DIR TALK [TALK ...] [--note TEXT]
    python -m dqi_sort.decide duplicate DATA_DIR KEEP TALK [TALK ...] [--note TEXT]

offer      we are trying to exchange the talk to another unit: status exchange_pending. It is set aside: out of its
           session and out of the pool, so no step places it while the unit decides.
exchanged  the other unit took it: status other_unit.
returned   the other unit declined: status active again, in the pool of lonely abstracts.
received   a talk brought in from another unit (it must already be in talks.csv: run intake on an APS export that
           includes it): status active, marked from_unit:UNIT in its flags, in the pool of lonely abstracts. Build
           its card and embedding next (cards prepare --ids, embed).
poster     the talk becomes a poster: status poster.
keep       the talk stays in DQI's oral program: its row in sorting/held.csv is removed; if it is in no session it
           is a lonely abstract.
duplicate  the talks are another entry of KEEP (for example an invited placeholder and the real submission): status
           duplicate, out of their sessions. Keep the entry with more information.

Every change is appended to sorting/status_log.csv (when, talk_id, from_status, to_status, unit, by, note) and to
the move ledger (sorting/moves.csv); sorting/assignments.csv, sorting/held.csv and views/flags.md are updated.
Virtual talks are never offered, exchanged or made posters (the virtual track keeps every talk).
"""
import argparse, csv, datetime, json, os, sys
from dqi_sort import areas as A, sessions as S

LOG_COLS = ['when', 'talk_id', 'from_status', 'to_status', 'unit', 'by', 'note']
MOVE_COLS = ['when', 'commit', 'talk_id', 'from', 'to', 'by', 'reason']
# action: (statuses allowed before, status after)
RULES = {'offer': ({'active'}, 'exchange_pending'), 'exchanged': ({'exchange_pending'}, 'other_unit'),
         'returned': ({'exchange_pending'}, 'active'), 'received': ({'active'}, 'active'),
         'poster': ({'active', 'exchange_pending'}, 'poster'), 'keep': ({'active'}, 'active'),
         'duplicate': ({'active', 'exchange_pending'}, 'duplicate')}


def write_csv(path, cols, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, extrasaction='ignore', lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def append_csv(path, cols, rows):
    new = not os.path.exists(path)
    with open(path, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, extrasaction='ignore', lineterminator='\n')
        if new:
            w.writeheader()
        w.writerows(rows)


def last_unit(log, i):
    return next((r['unit'] for r in reversed(log) if r['talk_id'] == i and r['unit']), '')


def decide(data_dir, action, ids, unit='', note='', by='lead'):
    before, after = RULES[action]
    keep_id = ''
    if action == 'duplicate':                     # unit carries the kept talk's ID here
        keep_id, unit = unit, ''
        note = note or f'duplicate of {keep_id}'
    if action in ('offer', 'received') and not unit:
        sys.exit(f'{action} needs the unit')
    tpath = os.path.join(data_dir, 'talks.csv')
    rows = S.read_csv(tpath)
    cols = list(rows[0])
    talks = {r['talk_id']: r for r in rows}
    sdir = os.path.join(data_dir, 'sorting')
    lpath = os.path.join(sdir, 'status_log.csv')
    log = S.read_csv(lpath) if os.path.exists(lpath) else []
    bad = [f'{i}: not in talks.csv' + (' (run intake on an APS export that includes it)' if action == 'received' else '')
           for i in ids if i not in talks]
    bad += [f"{i}: status is {talks[i]['status']}; {action} needs {' or '.join(sorted(before))}" for i in ids
            if i in talks and talks[i]['status'] not in before]
    bad += [f'{i}: virtual talks stay in the virtual track' for i in ids
            if i in talks and talks[i]['track'] == 'virtual' and action in ('offer', 'poster')]
    if bad:
        sys.exit('nothing changed:\n' + '\n'.join(bad))
    now = datetime.datetime.now().isoformat(timespec='minutes')
    apath = os.path.join(sdir, 'assignments.csv')
    assign = {r['talk_id']: r for r in S.read_csv(apath)} if os.path.exists(apath) else {}
    held = A.read_held(data_dir)
    new_log, moves, short = [], [], []
    for i in ids:
        t = talks[i]
        u = unit or last_unit(log, i)
        a = assign.setdefault(i, {'talk_id': i, 'session_id': '', 'order': '', 'locked': 'false', 'note': ''})
        where = a['session_id'] or 'lonely'
        if action in ('offer', 'exchanged', 'poster', 'duplicate'):
            to = {'offer': f'{u} (offered)', 'exchanged': u, 'poster': 'poster', 'duplicate': f'duplicate of {keep_id}'}[action]
            if a['session_id']:
                short.append(a['session_id'])
            a.update(session_id='', order='', note={'offer': f'offered to {u} ({now[:10]})', 'exchanged': f'exchanged to {u} ({now[:10]})',
                                                    'poster': f'poster ({now[:10]})', 'duplicate': f'duplicate of {keep_id}'}[action])
            moves.append((where if action != 'exchanged' else f'{u} (offered)', to))
        elif action == 'returned':
            a.update(session_id='', order='', note=f'returned by {u} ({now[:10]}): lonely')
            moves.append((f'{u} (offered)', 'lonely'))
        elif action == 'received':
            flags = set(filter(None, t['flags'].split(';'))) | {f'from_unit:{u}'}
            t['flags'] = ';'.join(sorted(flags))
            a.update(session_id='', order='', note=f'received from {u} ({now[:10]}): lonely')
            moves.append((u, 'lonely'))
        else:
            moves.append(None)
        new_log.append({'when': now, 'talk_id': i, 'from_status': t['status'] if action != 'received' else f'in {u}',
                        'to_status': after, 'unit': u if action in ('offer', 'exchanged', 'returned', 'received') else '',
                        'by': by, 'note': note})
        t['status'] = after
    write_csv(tpath, cols, rows)
    append_csv(lpath, LOG_COLS, new_log)
    mv = [{'when': now[:10], 'commit': '', 'talk_id': i, 'from': m[0], 'to': m[1], 'by': by,
           'reason': f'{action}' + (f': {note}' if note else '')} for i, m in zip(ids, moves) if m]
    if mv:
        append_csv(os.path.join(sdir, 'moves.csv'), MOVE_COLS, mv)
    if assign:
        write_csv(apath, ['talk_id', 'session_id', 'order', 'locked', 'note'], sorted(assign.values(), key=lambda r: S.id_key(r['talk_id'])))
    A.write_held(data_dir, [r for r in held if r['talk_id'] not in ids])
    spath = os.path.join(data_dir, 'work', 'pack', 'state.json')
    if os.path.exists(spath) and after != 'active':      # keep the global pass's working state consistent
        with open(spath, encoding='utf-8') as f:
            st = json.load(f)
        for s in st['sessions']:
            s['talks'] = [x for x in s['talks'] if x not in ids]
        st['pool'] = [p for p in st['pool'] if p['id'] not in ids]
        with open(spath, 'w', encoding='utf-8') as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    A.flags(data_dir)
    print(f"{len(ids)} talks: {action} -> status {after}; recorded in sorting/status_log.csv; views/flags.md rewritten")
    if short:
        print('sessions that lost a talk (top up at review, or from the pool):', ', '.join(sorted(set(short))))
    if action == 'received':
        print('next: build their cards and embeddings (cards prepare --ids, embed)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=list(RULES))
    ap.add_argument('data_dir')
    ap.add_argument('args', nargs='+', help='UNIT then talk IDs for offer and received; talk IDs otherwise')
    ap.add_argument('--note', default='')
    ap.add_argument('--by', default='lead')
    a = ap.parse_args()
    unit, ids = (a.args[0], a.args[1:]) if a.action in ('offer', 'received', 'duplicate') else ('', a.args)
    if not ids:
        sys.exit('no talk IDs given')
    decide(a.data_dir, a.action, ids, unit, a.note, a.by)


if __name__ == '__main__':
    main()
