import numpy as np
from dqi_sort import areas as Ar

AREAS = {'A': {'name': 'a', 'categories': ['1']}, 'B': {'name': 'b', 'categories': ['2']}, 'VIRTUAL': {'name': 'v', 'categories': []}}


def talk(track='in_person', series='', part=''):
    return {'track': track, 'series': series, 'series_part': part, 'minutes': '12', 'flags': '', 'title': 't', 'type': 'oral'}


def test_assign_moves_by_neighbours_and_keeps_series():
    ids = [str(1000000 + k) for k in range(14)]
    talks = {i: talk() for i in ids}
    cards = {i: {'best_category': '1' if k < 12 else '2'} for k, i in enumerate(ids)}
    talks[ids[13]] = talk(series='S1', part='2'); talks[ids[0]] = talk(series='S1', part='1')
    talks['2000000'] = talk(track='virtual'); cards['2000000'] = {'best_category': '1'}
    X = np.ones((15, 2)) / np.sqrt(2)                     # everyone is everyone's neighbour
    area, moves = Ar.assign(talks, cards, AREAS, ids + ['2000000'], X)
    assert area['2000000'] == 'VIRTUAL'
    assert area[ids[12]] == 'A'                           # category says B, all neighbours are A
    assert area[ids[13]] == area[ids[0]] == 'A'           # series part follows part 1
    assert any(m[0] == ids[12] for m in moves)


def test_modality_blocks_cross_platform_moves():
    areas = {'SC': {'name': 's', 'categories': ['1'], 'modality': 'superconducting'},
             'AMO': {'name': 'a', 'categories': ['2'], 'modality': 'amo'}, 'VIRTUAL': {'name': 'v', 'categories': []}}
    ids = [str(1000000 + k) for k in range(13)]
    talks = {i: talk() for i in ids}
    cards = {i: {'best_category': '1', 'platform': 'transmon'} for i in ids}
    cards[ids[11]] = {'best_category': '2', 'platform': 'trapped-ion bosonic mode'}     # neighbours SC, platform ions: stays
    cards[ids[12]] = {'best_category': '2', 'platform': 'fluxonium qubit'}              # filed under AMO, platform SC: moves
    X = np.ones((13, 2)) / np.sqrt(2)
    area, moves = Ar.assign(talks, cards, areas, ids, X)
    assert area[ids[11]] == 'AMO' and area[ids[12]] == 'SC'
