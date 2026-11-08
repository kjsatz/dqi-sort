"""The whole sort on one page, from one commit of the data repo.

    python -m dqi_sort.overview DATA_DIR [--commit REF] [--out PATH] [--no-attendance]

Reads the data exactly as it is in commit REF (default HEAD; uncommitted changes are ignored) and writes one
self-contained HTML page (default DATA_DIR/views/overview.html). The page holds abstracts, so it belongs in the
private data repo; open it in a browser (it needs no network).

On the page each review area is a column and each session an entry: its title, a dial for its expected attendance,
and a bar with one square per contributed talk and a triple-width box per invited talk, with outlined squares for
the minutes still free. Hover a talk (or tap it) for its details and abstract; click to pin the popup.

- Fit (the talk's colour): cosine similarity of the talk's card embedding to the centroid of the rest of its session
  (leave-one-out), the per-talk value behind the packing report's coherence. About 0.85 is unrelated, 0.95 very
  close (docs/sessions.md). Coloured on matplotlib's Spectral map over pack.FIT_RANGE: red a poor fit, blue a good one. The popup also gives the closest other session of the same track.
- Dial: the session's rank by the attendance model's estimate among the in-person sessions, from 0 (lowest) to 1
  (highest), with the spread-matched estimate in the popup (docs/attendance.md). Needs Ollama; virtual sessions have
  none.
"""
import argparse, datetime, io, json, os, re, subprocess, sys, tarfile, tempfile
import numpy as np

from dqi_sort import sessions as S, pack, sheets

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'overview_page.html')
PATHS = ['config.yaml', 'talks.csv', 'cards.jsonl', 'abstracts.jsonl', 'embeddings', 'sorting', 'history']


def git(data_dir, *args):
    return subprocess.run(['git', '-C', data_dir, *args], capture_output=True, check=True).stdout


def export(data_dir, ref, dest):
    """Write the files the page needs, as they are in commit `ref`, into `dest`."""
    have = set(git(data_dir, 'ls-tree', '--name-only', ref).decode().split())
    tar = git(data_dir, 'archive', ref, '--', *[p for p in PATHS if p in have])
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dest, filter='data')


def commit_info(data_dir, ref):
    out = git(data_dir, 'log', '-1', '--format=%h%x09%cI%x09%s', '--abbrev=7', ref).decode().strip()
    h, when, subject = out.split('\t', 2)
    when = datetime.datetime.fromisoformat(when)
    return {'hash': h, 'date': f'{when:%b} {when.day}, {when:%Y %H:%M}', 'subject': subject}


def fits(data_dir, sess, talks):
    """{talk_id: (fit, closest other session, its similarity)}; see the module docstring."""
    space = pack.Space(data_dir, None)
    track = {s['session_id']: talks[s['talks'][0]]['track'] for s in sess if s['talks']}
    cent = {s['session_id']: space.centroid(s['talks']) for s in sess}
    ids = [k for k, c in cent.items() if c is not None]
    C = np.array([cent[k] for k in ids])
    out = {}
    for s in sess:
        _, per = pack.coherence(space, s['talks'])
        for i, f in per.items():
            sims = C @ space.vec(i)
            best = max((j for j, k in enumerate(ids) if k != s['session_id'] and track[k] == track.get(s['session_id'])),
                       key=lambda j: sims[j], default=None)
            out[i] = (round(f, 3), ids[best] if best is not None else '', round(float(sims[best]), 3) if best is not None else None)
    return out


def dials(est):
    """{session_id: rank of its estimate among `est`, 0 (lowest) to 1 (highest); ties share their mean rank}."""
    keys = list(est)
    if not keys:
        return {}
    vals = np.array([est[k].get('model', est[k]['interest']) for k in keys], float)
    order = np.argsort(vals, kind='stable')
    rank = np.empty(len(vals)); rank[order] = np.arange(len(vals))
    for v in np.unique(vals):
        rank[vals == v] = rank[vals == v].mean()
    return {k: round(float(r / max(1, len(keys) - 1)), 3) for k, r in zip(keys, rank)}


def payload(data_dir, info, attendance=True):
    cfg = S.load_config(data_dir)
    talks, cards, sess, _, lonely, _ = sheets.load(data_dir)
    fit = fits(data_dir, sess, talks)
    in_person = [s for s in sess if s['talks'] and talks[s['talks'][0]]['track'] == 'in_person']
    est = S.estimates(data_dir, in_person, cfg) if attendance else {}
    dial = dials(est)
    names = {a: (v or {}).get('name', '') for a, v in (cfg.get('areas') or {}).items()}
    order = [a for a in names if any(s['area'] == a for s in sess)]
    order += sorted({s['area'] for s in sess} - set(order))
    titles = {s['session_id']: s['title'] for s in sess}

    def talk(i):
        t, c = talks[i], cards.get(i) or {}
        f = fit.get(i, (None, '', None))
        return {'id': i, 'title': t['title'], 'speaker': t['speaker'], 'inst': t['institution'] or t['affiliation'],
                'type': t['type'], 'units': S.units(t), 'cat': t['submitted_category'], 'best': c.get('best_category', ''),
                'fit': f[0], 'other': f[1], 'other_title': titles.get(f[1], ''), 'other_fit': f[2],
                'summary': c.get('key_claim', ''), 'abstract': t.get('abstract', ''),
                'series': f"{t['series']} part {t['series_part']}" if t.get('series') else ''}

    areas = []
    for a in order:
        mine = sorted((s for s in sess if s['area'] == a), key=lambda s: S.id_key(s['session_id']))
        rows = []
        for s in mine:
            e = est.get(s['session_id'])
            per = [fit[i][0] for i in s['talks'] if i in fit]
            rows.append({'id': s['session_id'], 'title': s['title'], 'kind': s['kind'], 'minutes': int(s['minutes']),
                         'units': int(s['minutes']) // S.UNIT_MIN, 'scope': s.get('scope', ''),
                         'coherence': round(float(np.mean(per)), 3) if per else None,
                         'estimate': {k: e[k] for k in ('interest', 'low', 'high')} if e else None,
                         'dial': dial.get(s['session_id']), 'talks': [talk(i) for i in s['talks']]})
        areas.append({'code': a, 'name': names.get(a, ''), 'sessions': rows})
    year = re.search(r'\b(20\d\d)\b', str(cfg.get('meeting_dates', '')))
    return {'year': year.group(1) if year else '', 'commit': info, 'fit_range': pack.FIT_RANGE,
            'categories': cfg.get('dqi_categories') or {}, 'areas': areas,
            'unplaced': [talk(a['talk_id']) for a in lonely], 'n_estimated': len(dial)}


def render(data):
    with open(TEMPLATE, encoding='utf-8') as f:
        page = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    title = f"DQI {data['year']} sort overview".replace('  ', ' ')
    return page.replace('__TITLE__', title).replace('__DATA__', blob)


def build(data_dir, ref='HEAD', out=None, attendance=True):
    info = commit_info(data_dir, ref)
    with tempfile.TemporaryDirectory() as tmp:
        export(data_dir, info['hash'], tmp)
        page = render(payload(tmp, info, attendance))
    out = out or os.path.join(data_dir, 'views', 'overview.html')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f"wrote {out} from commit {info['hash']} ({info['subject']})")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--commit', default='HEAD', help='the data repo commit to show (default HEAD)')
    ap.add_argument('--out', help='output file (default DATA_DIR/views/overview.html)')
    ap.add_argument('--no-attendance', action='store_true', help='skip the attendance dials (no Ollama needed)')
    a = ap.parse_args()
    try:
        build(a.data_dir, a.commit, a.out, not a.no_attendance)
    except subprocess.CalledProcessError as e:
        sys.exit(f"git failed: {e.stderr.decode().strip()}")


if __name__ == '__main__':
    main()
