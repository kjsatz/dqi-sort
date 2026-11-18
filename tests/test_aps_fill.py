"""aps_fill: plan the writes into a made-up copy of APS's 2027 tab, then compare a read-back."""
from dqi_sort import aps_fill as A

SH = ['Session Type (auto)', 'Length', 'Abbreviation', 'Session Title', '# Talks', 'Slots', 'Seats Left', 'x', 'y',
      'Chair Name', 'Chair Email', 'Chair Affiliation', 'Co-Chair Name (optional)', 'Co-Chair Email (optional)',
      'Co-Chair Affiliation (optional)']
TH = ['ID', 'Type', 'Presenter', 'Affiliation', 'Category', 'Title', 'Abstract Body', 'Special', 'Also', 'Vol', 'Session', 'Order', 'Sorter Notes']


def tab(n_rows=3):
    v = [['Title'], [], SH]
    v += [['=IF($C4="","",1)'] for _ in range(n_rows)]
    v += [[], ['ASSIGN THE TALKS'], TH]
    v += [['9001', 'Invited', 'Ada Example'] + [''] * 7, ['9002', 'Oral', 'Bo Example'] + [''] * 7,
          ['9003', 'Oral', 'Cy Example'] + [''] * 9 + ['moving to another unit']]
    return v


SESSIONS = [dict(sid='AAA01', minutes=144, title='First Session', kind='mini-symposium', chair='Dee Chair', email='dee@example.org',
                 aff='Example U', talks=['9002', '9001'], invited=1),
            dict(sid='AAA02', minutes=108, title='Second Session', kind='contributed', chair='Eve Chair', email='eve@example.org',
                 aff='Example Lab', talks=['9003'], invited=0)]
PLACE = {'9002': ('AAA01', 1), '9001': ('AAA01', 2), '9003': ('AAA02', 1)}


def apply(values, updates):
    import re
    v = [list(r) for r in values]
    for rng, rows in updates:
        m = re.match(r"'.*'!([A-Z]+)(\d+):([A-Z]+)(\d+)", rng)
        c = ord(m.group(1)) - 65
        for k, (x,) in enumerate(rows):
            i = int(m.group(2)) - 1 + k
            v[i] += [''] * (c + 1 - len(v[i]))
            v[i][c] = str(x)
    return v


def test_layout_finds_rows_by_headers():
    L = A.layout(tab())
    assert L['srows'] == [3, 4, 5]
    assert L['trows'] == {'9001': 9, '9002': 10, '9003': 11}
    assert L['scol']['abbr'] == 2 and L['scol']['co_chair'] == 12 and L['tcol']['session'] == 10


def test_plan_writes_sessions_talks_and_clears_spare_rows():
    v = tab()
    updates, probs = A.plan(v, SESSIONS, PLACE)
    assert probs == []
    out = apply(v, updates)
    assert out[3][1:4] == ['144', 'AAA01', 'First Session'] and out[3][9] == 'Dee Chair'
    assert out[5][2] == ''                                  # third session row cleared
    assert out[9][10:12] == ['AAA01', '2'] and out[10][10:12] == ['AAA01', '1']
    assert out[11][12] == 'moving to another unit'         # APS's sorter note kept
    for i in (3, 4):                                       # APS's formulas fill these on the real sheet
        out[i][4], out[i][6] = str(len(SESSIONS[i - 3]['talks'])), '3'
        out[i][0] = 'Mini-symposium' if SESSIONS[i - 3]['invited'] else 'Oral Contributed'
    assert A.compare(out, SESSIONS, PLACE, A.layout(v)) == []


def test_plan_refuses_someone_elses_session():
    v = tab()
    v[4] += ['144', 'ZZZ09', 'Not ours']
    updates, probs = A.plan(v, SESSIONS, PLACE)
    assert updates == [] and 'ZZZ09' in probs[0]
    updates, _ = A.plan(v, SESSIONS, PLACE, force=True)
    assert updates


def test_compare_reports_mismatches():
    v = tab()
    out = apply(v, A.plan(v, SESSIONS, PLACE)[0])
    out[10][11] = '3'                                      # wrong order
    out[4][3] = 'Retitled'                                 # wrong title
    out[4][6] = '-1'                                       # over capacity
    probs = A.compare(out, SESSIONS, PLACE, A.layout(v))
    assert any('talk 9002' in p for p in probs)
    assert any('AAA02: Session Title' in p for p in probs)
    assert any('over capacity' in p for p in probs)


def test_in_person_errors_skip_the_virtual_track():
    d = dict(sess={'V1': {'area': 'VIRTUAL'}, 'P1': {'area': 'X'}}, talks={'1': {'track': 'virtual'}, '2': {'track': 'in_person'}},
             aps={'virtual': (['ID'], [['3']], 0)})
    probs = [('ERROR', 'V1: 0 of 2 chairs'), ('ERROR', '3: in the APS input but not in talks.csv'), ('ERROR', 'P1: no chair'),
             ('ERROR', '2: twice'), ('WARN', 'P1: empty')]
    assert A.in_person_errors(d, probs) == ['P1: no chair', '2: twice']
