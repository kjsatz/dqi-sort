import collections, csv
from dqi_sort import mockgrid

TALK_COLS = ['talk_id', 'track', 'type', 'minutes', 'status', 'time_windows']


def data(tmp_path, cfg='virtual_session_min: 84\n'):
    (tmp_path / 'config.yaml').write_text(cfg)
    rows = [dict(talk_id=str(1000000 + k), track='in_person', type='oral', minutes='12', status='active', time_windows='')
            for k in range(30)]
    rows += [dict(talk_id=str(2000000 + k), track='virtual', type='oral', minutes='12', status='active',
                  time_windows='06:30-07:54 ET;12:15-13:39 ET') for k in range(9)]
    with open(tmp_path / 'talks.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, TALK_COLS); w.writeheader(); w.writerows(rows)
    return tmp_path


def slots(d):
    return list(csv.DictReader(open(d / 'schedule' / 'slots.csv')))


def test_session_counts_from_aps(tmp_path):
    d = data(tmp_path)
    assert mockgrid.make(str(d), n_long=23, n_short=15) == 38
    s = slots(d)
    c = collections.Counter((x['track'], x['minutes']) for x in s)
    assert c[('in_person', '144')] == 23 and c[('in_person', '108')] == 15
    v = [x for x in s if x['track'] == 'virtual']
    assert v and all(x['minutes'] == '84' and x['start'] in ('06:30', '12:15') for x in v)
    assert {x['end'] for x in v} <= {'07:54', '13:39'}
    assert 'session counts' in (d / 'venue' / 'README.md').read_text()


def test_sized_to_talks_by_default(tmp_path):
    d = data(tmp_path, cfg='')
    mockgrid.make(str(d))
    s = slots(d)
    assert sum(int(x['minutes']) for x in s if x['track'] == 'in_person') >= 30 * 12
    assert all(x['minutes'] == '120' for x in s if x['track'] == 'virtual')


def test_virtual_windows_in_the_grid_match_the_speakers_format(tmp_path):
    from dqi_sort import sessions
    d = data(tmp_path)
    mockgrid.make(str(d), n_long=23, n_short=15)
    _, _, _, virtual = sessions.grid(str(d))
    assert set(virtual) == {'06:30-07:54', '12:15-13:39'}
    assert all(sessions.windows(w) == {w} for w in virtual)      # the check reads assumed windows in this form
