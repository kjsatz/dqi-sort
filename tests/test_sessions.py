from dqi_sort import sessions as S


def talk(type='oral', series='', part=0, inst='Univ A', win=()):
    return {'type': type, 'units': 3 if type == 'invited' else 1, 'series': series, 'part': part,
            'institution': inst, 'windows': list(win)}


def area(n_oral=21, n144=1, n108=1, **extra):
    info = {str(1000 + k): talk(inst=f'Univ {k % 5}') for k in range(n_oral)}
    limits = {'virtual': False, 'n144': n144, 'n108': n108, 'minutes': [144, 108], 'area': 'A', 'max_same_institution': 4}
    limits.update(extra)
    return {'limits': limits, 'talks': info}


def session(ids, minutes):
    return {'title': 'T', 'minutes': minutes, 'scope': 's', 'talks': ids, 'weakest_fits': []}


def test_share_uses_the_whole_grid_in_proportion():
    sh = S.share({'A': 400, 'B': 200, 'C': 100}, 40, 30)
    assert sum(a for a, b in sh.values()) == 40 and sum(b for a, b in sh.values()) == 30
    cap = {k: 12 * a + 9 * b for k, (a, b) in sh.items()}
    assert all(cap[k] >= u for k, u in {'A': 400, 'B': 200, 'C': 100}.items())


def test_valid_proposal_with_release_and_option():
    data = area()
    ids = sorted(data['talks'])
    p = {'sessions': [session(ids[:12], 144), session(ids[12:20], 108)],
         'released': [{'id': ids[20], 'reason': 'off topic', 'suggested_home': 'QEC'}],
         'options': [{'why': 'swap', 'replaces': [1, 2], 'sessions': [session(ids[:11], 144), session(ids[11:20], 108)]}]}
    err, warn = S.check_proposal(p, data)
    assert err == [] and warn == []                    # 1 of 21 units released is under the warning line


def test_errors_for_short_session_missing_talk_and_share():
    data = area()
    ids = sorted(data['talks'])
    p = {'sessions': [session(ids[:10], 144), session(ids[10:19], 108)], 'released': []}
    err, _ = S.check_proposal(p, data)
    assert any('empty units' in e for e in err)
    assert any('neither placed nor released' in e for e in err)
    p = {'sessions': [session(ids[:12], 144), session(ids[12:21], 144)], 'released': []}
    err, _ = S.check_proposal(p, data)
    assert any('share' in e for e in err)


def test_series_order_invited_limit_and_institution():
    data = area(n_oral=12)
    ids = sorted(data['talks'])
    data['talks'][ids[0]] = talk(series='S1', part=2)
    data['talks'][ids[5]] = talk(series='S1', part=1)
    for i in ids[1:4]:
        data['talks'][i] = talk('invited')
    p = {'sessions': [session(ids, 144)], 'released': []}
    err, _ = S.check_proposal(p, data)
    assert any('series S1' in e for e in err)
    assert any('invited' in e for e in err)
    data = area(n_oral=12)
    for i in data['talks']:
        data['talks'][i]['institution'] = 'Same'
    err, warn = S.check_proposal({'sessions': [session(sorted(data['talks']), 144)], 'released': []}, data)
    assert err == [] and any('Same' in w for w in warn)


def test_virtual_windows():
    info = {'1': talk(win=['05:30-07:30']), '2': talk(win=['10:30-12:30']), '3': talk()}
    data = {'limits': {'virtual': True, 'max_sessions': 3, 'minutes': [120], 'area': 'VIRTUAL', 'max_same_institution': 4},
            'talks': info}
    p = {'sessions': [session(['1', '2', '3'], 120)], 'released': []}
    err, _ = S.check_proposal(p, data)
    assert any('share no time window' in e for e in err) and any('assumed_windows' in e for e in err)
    p = {'sessions': [session(['1', '3'], 120), session(['2'], 120)], 'released': [], 'assumed_windows': {'3': '05:30-07:30 MDT'}}
    err, _ = S.check_proposal(p, data)
    assert err == []
