import collections
from dqi_sort import schedule as Sc


def test_allocate_fills_largest_rooms_by_interest_and_keeps_reviewer_sizes():
    sess = [{'session_id': f'S{k}', 'minutes': '144', 'size': ''} for k in range(5)]
    sess[4]['size'] = 'large'                                  # a reviewer's choice stands
    interest = {'S0': 50, 'S1': 200, 'S2': 120, 'S3': 90, 'S4': 10}
    have = collections.Counter({('large', 144): 2, ('medium', 144): 1, ('small', 144): 2})
    d = Sc.allocate(sess, interest, have)
    assert d == {'S4': 'large', 'S1': 'large', 'S2': 'medium', 'S3': 'small', 'S0': 'small'}
