import csv
import pytest
from dqi_sort import sessions

COLS = ['talk_id', 'track', 'type', 'minutes', 'status', 'time_windows']


def data(tmp_path, cfg):
    (tmp_path / 'config.yaml').write_text(cfg)
    rows = [dict(talk_id=str(2000000 + k), track='virtual', type='oral', minutes='12', status='active',
                 time_windows='06:30-07:54 ET;12:15-13:39 ET' if k % 2 else '09:30-10:54 ET') for k in range(9)]
    rows.append(dict(talk_id='2000099', track='virtual', type='invited', minutes='36', status='active', time_windows=''))
    with open(tmp_path / 'talks.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, COLS); w.writeheader(); w.writerows(rows)
    return str(tmp_path)


def test_counts_from_config_before_the_real_grid(tmp_path):
    d = data(tmp_path, 'session_slots: {144: 113, 108: 94}\nvirtual_session_min: 84\n')
    n144, n108, c, virtual = sessions.grid(d)
    assert (n144, n108) == (113, 94)
    assert set(virtual) == {'06:30-07:54', '09:30-10:54', '12:15-13:39'}     # the speakers' own windows, no made-up times
    assert all(sessions.windows(w) == {w} for w in virtual)
    assert c[('virtual', 84)] == 2 + 2                                       # 12 units fill 2 sessions of 7, plus spares


def test_no_grid_and_no_counts(tmp_path):
    d = data(tmp_path, 'virtual_session_min: 84\n')
    with pytest.raises(SystemExit):
        sessions.grid(d)


def test_real_grid_wins(tmp_path):
    d = data(tmp_path, 'session_slots: {144: 1, 108: 1}\n')
    (tmp_path / 'schedule').mkdir()
    (tmp_path / 'schedule' / 'slots.csv').write_text(
        'slot_id,track,day,start,end,minutes,room_id\nA,in_person,Mon,08:00,10:24,144,R1\nB,in_person,Mon,13:45,16:09,144,R1\n'
        'V,virtual,Mon,06:30,07:54,84,\n')
    n144, n108, _, virtual = sessions.grid(d)
    assert (n144, n108) == (2, 0) and set(virtual) == {'06:30-07:54'}
