import csv, json
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


def test_flags_lists_each_talk_once(tmp_path):
    d = tmp_path
    (d / 'sorting').mkdir()
    cols = ['talk_id', 'track', 'type', 'title', 'speaker', 'affiliation', 'institution', 'submitted_category', 'area', 'series',
            'series_part', 'flags', 'status']
    rows = [dict(zip(cols, [i, 'in_person', 'oral', f'title {i}', 'A B', 'U', 'U', '17.01.01', 'A', '', '', '', 'active'])) for i in ('1', '2', '3')]
    with open(d / 'talks.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    base = {'platform': 'p', 'problem': 'q', 'approach': 'theory', 'key_claim': 'k', 'keywords': ['a', 'b', 'c'],
            'leadership_review': None, 'promotional': None, 'other_unit': None, 'malformed': None}
    cards = {'1': dict(base, talk_id='1', leadership_review={'flag': 'f', 'reason': 'no science'}),
             '2': dict(base, talk_id='2', leadership_review={'flag': 'f', 'reason': 'contradicts physics'}),
             '3': dict(base, talk_id='3', promotional={'reason': 'vendor tool'})}
    (d / 'cards.jsonl').write_text(''.join(json.dumps(c) + '\n' for c in cards.values()))
    (d / 'abstracts.jsonl').write_text('')
    Ar.write_held(str(d), [{'talk_id': '1', 'stage': '4', 'action': 'poster', 'unit': '', 'reason': 'no scientific content'}])
    Ar.flags(str(d))
    text = (d / 'views' / 'flags.md').read_text()
    assert text.count('| 1 |') == 0 and '### 1: title 1' in text and 'make it a poster' in text   # held, with its card, not repeated
    assert '| 2 |' in text and '| 3 |' in text and 'Promotional (no action expected) (1)' in text
