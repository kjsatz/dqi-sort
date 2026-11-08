import collections
from dqi_sort import schedule as Sc


def test_allocate_fills_largest_rooms_by_interest_and_keeps_reviewer_sizes():
    sess = [{'session_id': f'S{k}', 'minutes': '144', 'size': ''} for k in range(5)]
    sess[4]['size'] = 'large'                                  # a reviewer's choice stands
    interest = {'S0': 50, 'S1': 200, 'S2': 120, 'S3': 90, 'S4': 10}
    have = collections.Counter({('large', 144): 2, ('medium', 144): 1, ('small', 144): 2})
    d = Sc.allocate(sess, interest, have)
    assert d == {'S4': 'large', 'S1': 'large', 'S2': 'medium', 'S3': 'small', 'S0': 'small'}


def test_day_requests_are_read_from_card_constraints():
    assert Sc.day_request('Not Friday') == ({'Fri'}, set())
    assert Sc.day_request('Not Monday or Friday; Part 2 should follow directly after') == ({'Mon', 'Fri'}, set())
    assert Sc.day_request('prefers Monday to Thursday; travelling on Friday') == ({'Fri'}, {'Mon', 'Tue', 'Wed', 'Thu'})
    assert Sc.day_request('as early as possible') == (set(), {'Mon', 'Tue'})
    assert Sc.day_request('after the theory talk') == (set(), set())
    assert Sc.day_request('Monday to Wednesday only (planned travel)') == ({'Thu', 'Fri'}, set())


def test_grid_rows_rooms_as_columns_with_requests_and_green_slots():
    slots = {'Mon-0800-L1': {'slot_id': 'Mon-0800-L1', 'track': 'in_person', 'day': 'Mon', 'start': '08:00', 'end': '10:24', 'room_id': 'L1'},
             'Mon-0800-S1': {'slot_id': 'Mon-0800-S1', 'track': 'in_person', 'day': 'Mon', 'start': '08:00', 'end': '10:24', 'room_id': 'S1'},
             'Tue-0800-L1': {'slot_id': 'Tue-0800-L1', 'track': 'in_person', 'day': 'Tue', 'start': '08:00', 'end': '10:24', 'room_id': 'L1'}}
    rooms = {'L1': {'name': 'Ballroom 1', 'capacity': '500', 'size': 'large'}, 'S1': {'name': 'Hall A 1', 'capacity': '144', 'size': 'small'}}
    sess = {'QEC01': {'title': 'Superconducting QEC', 'kind': 'mini-symposium'}, 'SPIN02': {'title': 'Shuttling', 'kind': 'contributed'}}
    cards = {'t1': {'constraints': 'Not Friday'}, 't2': {'constraints': None}}
    header, rows, green = Sc.grid_rows({'QEC01': 'Mon-0800-L1', 'SPIN02': 'Tue-0800-L1'}, slots, rooms, sess,
                                       {'QEC01': ['t1', 't2'], 'SPIN02': ['t2']}, cards)
    assert header == ['Room', 'Ballroom 1', 'Hall A 1'] and rows[0] == ['Capacity', '500 (large)', '144 (small)']
    assert rows[1] == ['Mon 08:00–10:24', 'Mini-Symposium\nQEC01\nSuperconducting QEC\n\nRequests: not Fri', '(open)']
    assert rows[2] == ['Tue 08:00–10:24', 'Contributed\nSPIN02\nShuttling', ''] and sorted(green) == [(1, 1), (1, 2), (2, 1)]


def test_allocate_keeps_mini_symposia_in_recorded_rooms():
    # 144-min: large 2 slots (1 recorded), small 2 slots (1 recorded); two mini-symposia, two contributed sessions
    sess = [{'session_id': k, 'minutes': '144', 'size': ''} for k in 'ABCD']
    interest = {'A': 400, 'B': 300, 'C': 200, 'D': 100}       # B and D are the mini-symposia
    have = {('large', 144): 2, ('small', 144): 2}
    have_rec = {('large', 144): 1, ('small', 144): 1}
    import collections
    d = Sc.allocate(sess, interest, collections.Counter(have), collections.Counter(have_rec), {'B', 'D'})
    assert collections.Counter(d.values()) == {'large': 2, 'small': 2}
    assert d['B'] == 'large' and d['D'] == 'small'           # each mini-symposium in a class with a recorded slot left
    assert d['A'] == 'large' and d['C'] == 'small'           # A takes the unrecorded large slot


def test_recording_problems_count_spare_long_slots_for_short_sessions():
    import collections
    from dqi_sort import sessions as S
    C = collections.Counter
    assert S.recording_problems(C({144: 51, 108: 46}), C({144: 54, 108: 46})) == []
    assert S.recording_problems(C({144: 50, 108: 48}), C({144: 54, 108: 46})) == []      # two 108s in spare 144s
    assert len(S.recording_problems(C({144: 64, 108: 33}), C({144: 54, 108: 46}))) == 1
    assert S.is_recorded({'recorded': 'no'}) is False and S.is_recorded({}) is True


def test_assumed_windows_from_the_committed_file(tmp_path):
    import os
    from dqi_sort import sessions as S
    d = str(tmp_path)
    assert S.assumed_windows(d) == {}
    S.write_assumed_windows(d, {'12': '06:30-07:54', '3': ['09:30-10:54', '12:15-13:39']})
    assert S.assumed_windows(d) == {'3': {'09:30-10:54', '12:15-13:39'}, '12': {'06:30-07:54'}}
    assert open(os.path.join(d, 'sorting', 'assumed_windows.csv')).read().splitlines()[1].startswith('3,')   # sorted by ID
