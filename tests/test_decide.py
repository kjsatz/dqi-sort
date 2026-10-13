import csv, json
from dqi_sort import areas as Ar, decide as D


def setup(d):
    (d / 'sorting').mkdir()
    cols = ['talk_id', 'track', 'type', 'minutes', 'title', 'speaker', 'affiliation', 'institution', 'submitted_category', 'area',
            'series', 'series_part', 'time_windows', 'status', 'flags', 'notes']
    rows = [dict(zip(cols, [i, 'in_person', 'oral', '12', f't{i}', 'A B', 'U', 'U', '17.01.01', 'A', '', '', '', 'active', '', '']))
            for i in ('1', '2', '3')]
    rows[2]['track'] = 'virtual'
    with open(d / 'talks.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    with open(d / 'sorting' / 'assignments.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['talk_id', 'session_id', 'order', 'locked', 'note'])
        w.writerows([['1', 'A01', '1', 'false', ''], ['2', '', '', 'false', 'held'], ['3', 'VIRTUAL01', '1', 'false', '']])
    base = {'platform': 'p', 'problem': 'q', 'approach': 'theory', 'key_claim': 'k', 'keywords': ['a', 'b', 'c'],
            'leadership_review': None, 'promotional': None, 'other_unit': None, 'malformed': None}
    (d / 'cards.jsonl').write_text(''.join(json.dumps(dict(base, talk_id=i)) + '\n' for i in ('1', '2', '3')))
    (d / 'abstracts.jsonl').write_text('')
    Ar.write_held(str(d), [{'talk_id': '2', 'stage': '6', 'action': 'other_unit', 'unit': 'DCMP', 'reason': 'x'}])


def status(d):
    return {r['talk_id']: r['status'] for r in csv.DictReader(open(d / 'talks.csv'))}


def test_exchange_cycle_and_log(tmp_path):
    d = tmp_path; setup(d)
    D.decide(str(d), 'offer', ['1', '2'], unit='DCMP', note='asked their chair')
    assert status(d)['1'] == status(d)['2'] == 'exchange_pending'
    assign = {r['talk_id']: r for r in csv.DictReader(open(d / 'sorting' / 'assignments.csv'))}
    assert assign['1']['session_id'] == '' and Ar.read_held(str(d)) == []
    assert 'Offered to another unit, waiting (2)' in (d / 'views' / 'flags.md').read_text()
    D.decide(str(d), 'exchanged', ['1'])
    D.decide(str(d), 'returned', ['2'])
    assert status(d)['1'] == 'other_unit' and status(d)['2'] == 'active'
    log = list(csv.DictReader(open(d / 'sorting' / 'status_log.csv')))
    assert [(r['talk_id'], r['to_status'], r['unit']) for r in log] == [
        ('1', 'exchange_pending', 'DCMP'), ('2', 'exchange_pending', 'DCMP'), ('1', 'other_unit', 'DCMP'), ('2', 'active', 'DCMP')]
    assert all(r['when'] for r in log)


def test_refusals(tmp_path):
    d = tmp_path; setup(d)
    import pytest
    with pytest.raises(SystemExit):
        D.decide(str(d), 'offer', ['3'], unit='DCMP')          # virtual talks stay
    with pytest.raises(SystemExit):
        D.decide(str(d), 'exchanged', ['1'])                    # never offered
    with pytest.raises(SystemExit):
        D.decide(str(d), 'received', ['99'], unit='DAMOP')      # not in talks.csv yet


def test_duplicate(tmp_path):
    d = tmp_path; setup(d)
    D.decide(str(d), 'duplicate', ['2'], unit='1')
    assert status(d)['2'] == 'duplicate' and Ar.read_held(str(d)) == []
    log = list(csv.DictReader(open(d / 'sorting' / 'status_log.csv')))
    assert log[-1]['note'] == 'duplicate of 1'


def test_reinstate_returns_to_its_session(tmp_path):
    d = tmp_path; setup(d)
    with open(d / 'sorting' / 'sessions.csv', 'w') as f:
        f.write('session_id,title\nA01,a\n')
    D.decide(str(d), 'duplicate', ['1'], unit='2')
    D.decide(str(d), 'reinstate', ['1'])
    assign = {r['talk_id']: r for r in csv.DictReader(open(d / 'sorting' / 'assignments.csv'))}
    assert status(d)['1'] == 'active' and assign['1']['session_id'] == 'A01'


def test_decide_before_any_sort(tmp_path):
    d = tmp_path; setup(d)
    import shutil
    shutil.rmtree(d / 'sorting')                 # stage 3 or 4: no sorting folder yet
    D.decide(str(d), 'duplicate', ['2'], unit='1')
    assert status(d)['2'] == 'duplicate' and (d / 'sorting' / 'status_log.csv').exists()
