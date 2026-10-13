import collections
from dqi_sort import pack as P


def fake(sessions, pool=(), n144=2, n108=2, talks=None):
    srt = object.__new__(P.Sort)
    srt.talks = talks or {}
    srt.cfg = {'max_same_institution': 4}
    srt.n144, srt.n108 = n144, n108
    srt.parts = collections.defaultdict(list)
    for i, t in srt.talks.items():
        if t['series']:
            srt.parts[t['series']].append(i)
    for v in srt.parts.values():
        v.sort(key=lambda i: int(srt.talks[i]['series_part']))
    srt.state = {'sessions': sessions, 'pool': list(pool), 'virtual': [], 'next_new': 1, 'round': 1}
    return srt


def talk(minutes=12, series='', part='', typ='oral', inst='U'):
    return {'minutes': str(minutes), 'series': series, 'series_part': part, 'type': typ, 'institution': inst, 'affiliation': inst}


def test_choose_lengths_respects_slot_counts():
    lengths = P.choose_lengths({'a': 12, 'b': 11, 'c': 9, 'd': 10}, n144=2, n108=2)
    assert lengths['a'] == lengths['b'] == 144 and lengths['c'] == 108
    assert P.cost(10, 108) == 1 and P.cost(10, 144) == 1 and P.cost(8, 108) == 0


def test_moves_keep_series_together_and_check_fits():
    talks = {str(k): talk() for k in range(1, 25)}
    talks['23'] = talk(series='S1', part='1'); talks['24'] = talk(series='S1', part='2')
    sess = [{'id': 'A01', 'title': 'a', 'scope': '', 'area': 'A', 'talks': [str(k) for k in range(1, 12)]},
            {'id': 'A02', 'title': 'b', 'scope': '', 'area': 'A', 'talks': [str(k) for k in range(12, 21)] + ['23', '24']}]
    srt = fake(sess, [{'id': '21', 'from': 'A', 'reason': 'r', 'suggested_home': ''}, {'id': '22', 'from': 'A', 'reason': 'r', 'suggested_home': ''}],
               n144=2, n108=0, talks=talks)
    c = P.check(srt)
    assert not c['fits']
    log, err = P.apply_ops(srt, [{'op': 'move', 'talk': '24', 'to': 'A01', 'reason': 'x'},
                                 {'op': 'move', 'talk': '21', 'to': 'A02', 'reason': 'x'},
                                 {'op': 'move', 'talk': '22', 'to': 'A02', 'reason': 'x'}])
    assert err == []
    assert srt.session('A01')['talks'][-2:] == ['23', '24']          # the whole series moved, in order
    c = P.check(srt)
    assert c['units'] == {'A01': 13, 'A02': 11} and c['delta']['A01'] == -1
    log, err = P.apply_ops(srt, [{'op': 'move', 'talk': '1', 'to': 'A02', 'reason': 'x'}])
    assert P.check(srt)['fits']


def test_new_dissolve_hold_and_errors():
    talks = {str(k): talk() for k in range(1, 10)}
    sess = [{'id': 'A01', 'title': 'a', 'scope': '', 'area': 'A', 'talks': [str(k) for k in range(1, 10)]}]
    srt = fake(sess, talks=talks)
    log, err = P.apply_ops(srt, [{'op': 'new', 'title': 'N', 'talks': ['1', '2'], 'reason': 'x'},
                                 {'op': 'dissolve', 'session': 'X01', 'reason': 'x'},
                                 {'op': 'hold', 'talk': '1', 'reason': 'not DQI'},
                                 {'op': 'move', 'talk': '3', 'to': 'nowhere', 'reason': 'x'},
                                 {'op': 'move', 'talk': '4', 'to': 'pool'}])
    assert len(err) == 2
    assert [p['id'] for p in srt.state['pool']] == ['1', '2'] and srt.state['pool'][0]['hold']
