"""aps_input: reading APS's sorting sheet (made-up rows), the format check and the snapshot diff."""
from dqi_sort import aps_input as A

HEAD = ['ID', 'Type', 'Presenter', 'Affiliation', 'Category', 'Title', 'Abstract Body', 'Session', 'Order', 'Sorter Notes']


def tab(*rows):
    return [['Some title'], [], HEAD] + [list(r) for r in rows]


CFG = {'aps_columns': {h: h.lower() for h in HEAD}, 'aps_types': {'Oral': 'oral', 'Invited': 'invited'},
       'dqi_categories': {'99.01.01': 'Made-up category'}}


def test_table_finds_header_and_talk_rows():
    h, rows = A.table(tab(['101', 'Oral', 'Ada Example'], ['note row'], [102.0, 'Invited', 'Bo Example']))
    assert h == HEAD
    assert [r['ID'] for r in rows] == ['101', '102'] and rows[1]['Presenter'] == 'Bo Example'


def test_read_tracks_matches_tab_names_and_prefixes():
    vals = {'In-Person 1': tab(['101', 'Oral']), 'In-Person 2': tab(['102', 'Oral']), 'Virtual Sorting': tab(['201', 'Oral']),
            'Start Here': [['x']]}
    t = A.read_tracks(vals, {'in_person': 'In-Person*', 'virtual': 'Virtual Sorting', 'spark': 'SPARK*'})
    assert [r['ID'] for r in t['in_person'][1]] == ['101', '102'] and t['in_person'][1][1]['Tab'] == 'In-Person 2'
    assert [r['ID'] for r in t['virtual'][1]] == ['201'] and t['spark'] == ([], [])


def test_problems_and_notes():
    vals = {'In-Person': tab(['101', 'Oral', 'A', '', '99.01.01'], ['102', 'Poster', 'B', '', '12.01.01']),
            'Virtual': tab(['101', 'Oral']), 'SPARK': tab(['301', 'Oral'])}
    t = A.read_tracks(vals, {'in_person': 'In-Person', 'virtual': 'Virtual', 'spark': 'SPARK'})
    probs = A.problems(t, CFG)
    assert any('SPARK tab has 1' in p for p in probs)
    assert any('talk 101 is on both' in p for p in probs)
    assert any('types not in config aps_types: Poster' in p for p in probs)
    assert any('12.01.01' in n for n in A.notes(t, CFG))


def test_compare_lists_added_gone_changed():
    old = {'1': {'Presenter': 'A', 'Title': 'T1'}, '2': {'Presenter': 'B', 'Title': 'T2'}}
    new = {'1': {'Presenter': 'A2', 'Title': 'T1'}, '3': {'Presenter': 'C', 'Title': 'T3'}}
    lines = A.compare(old, new)
    assert any(l.startswith('  added   3') for l in lines) and any(l.startswith('  gone    2') for l in lines)
    assert any('changed 1' in l and 'Presenter' in l for l in lines)
