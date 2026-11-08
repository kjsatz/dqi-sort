import csv, json, os, subprocess

import numpy as np

from dqi_sort import overview as O

TALK_COLS = ['talk_id', 'track', 'type', 'minutes', 'title', 'speaker', 'affiliation', 'institution', 'submitted_category',
             'area', 'series', 'series_part', 'time_windows', 'status', 'flags', 'notes']


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)


def make_repo(d):
    """A made-up data repo: two sessions of an area A; talk 3 belongs with neither; talk 2's title holds a </script>."""
    talks = [dict(talk_id=str(i), track='in_person', type='invited' if i == 1 else 'oral', minutes='36' if i == 1 else '12',
                  title=f'Talk {i}', speaker=f'Speaker {i}', affiliation='Uni', institution='Uni', submitted_category='99.01.01',
                  area='A', series='', series_part='', time_windows='', status='active', flags='', notes='') for i in range(1, 6)]
    talks[1]['title'] = 'Talk </script> 2'
    write_csv(os.path.join(d, 'talks.csv'), TALK_COLS, talks)
    with open(os.path.join(d, 'cards.jsonl'), 'w') as f:
        for t in talks:
            f.write(json.dumps({'talk_id': t['talk_id'], 'key_claim': 'Claim ' + t['talk_id'], 'best_category': '99.01.01'}) + '\n')
    with open(os.path.join(d, 'abstracts.jsonl'), 'w') as f:
        f.write(json.dumps({'talk_id': '2', 'body': '<p>We show &mu;s.</p>'}) + '\n')
    write_csv(os.path.join(d, 'sorting', 'sessions.csv'), ['session_id', 'title', 'kind', 'minutes', 'size', 'area', 'locked', 'scope', 'notes'],
              [dict(session_id='A01', title='First', kind='mini-symposium', minutes='108', size='', area='A', locked='false', scope='S', notes=''),
               dict(session_id='A02', title='Second', kind='contributed', minutes='108', size='', area='A', locked='false', scope='', notes='')])
    write_csv(os.path.join(d, 'sorting', 'assignments.csv'), ['talk_id', 'session_id', 'order', 'locked', 'note'],
              [dict(talk_id=str(i), session_id='A01' if i <= 3 else 'A02', order=str(i), locked='false', note='') for i in range(1, 6)])
    os.makedirs(os.path.join(d, 'embeddings'))
    X = np.array([[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0], [0, 0, 1], [0.1, 0, 0.9]], np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    np.savez(os.path.join(d, 'embeddings', 'cards.npz'), talk_id=np.array([t['talk_id'] for t in talks]), vector=X, meta=json.dumps({}))
    with open(os.path.join(d, 'config.yaml'), 'w') as f:
        f.write('meeting_dates: "April 1-2, 2099"\nareas:\n  A: {name: "Area A", categories: []}\n')
    for args in (['init', '-q'], ['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'data']):
        subprocess.run(['git', '-C', d, *args], check=True)


def test_page_from_a_commit_ignores_later_edits(tmp_path):
    d = str(tmp_path / 'data')
    os.makedirs(d)
    make_repo(d)
    with open(os.path.join(d, 'talks.csv'), 'a') as f:      # uncommitted: not on the page
        f.write('99,in_person,oral,12,Uncommitted,X,U,U,99.01.01,A,,,,active,,\n')
    out = O.build(d, attendance=False)
    page = open(out, encoding='utf-8').read()
    blob = page.split('<script type="application/json" id="data">')[1].split('</script>')[0]
    data = json.loads(blob)
    assert data['year'] == '2099' and data['commit']['subject'] == 'data'
    s1, s2 = data['areas'][0]['sessions']
    assert [t['id'] for t in s1['talks']] == ['1', '2', '3'] and s1['units'] == 9 and s1['dial'] is None
    t1, t2, t3 = s1['talks']
    assert t1['units'] == 3 and t1['type'] == 'invited'
    assert t3['fit'] < 0.1 < t1['fit'] and t3['other'] == 'A02'          # talk 3 is the odd one out
    assert t2['abstract'] == 'We show μs.' and t2['title'] == 'Talk </script> 2' and t2['summary'] == 'Claim 2'
    assert 'Uncommitted' not in page and '<title>DQI 2099 sort overview</title>' in page
    assert page.count('</script>') == 2                     # the title's </script> is escaped inside the data


def test_dials_rank_from_zero_to_one_with_ties():
    est = {'a': {'interest': 50}, 'b': {'interest': 200, 'model': 90}, 'c': {'interest': 120, 'model': 90}, 'd': {'interest': 10, 'model': 300}}
    d = O.dials(est)
    assert d['a'] == 0.0 and d['d'] == 1.0 and d['b'] == d['c'] == 0.5      # ranked on the model's own number
    assert O.dials({}) == {}
