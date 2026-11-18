import json, os

from dqi_sort import schedule_page as P
from tests.test_overview import make_repo


def test_page_from_a_schedule_with_symposia_and_room_lines(tmp_path):
    d = str(tmp_path / 'data')
    os.makedirs(d)
    make_repo(d)
    os.makedirs(os.path.join(d, 'venue')); os.makedirs(os.path.join(d, 'schedule'))
    open(os.path.join(d, 'venue', 'rooms.csv'), 'w').write(
        'room_id,name,capacity,size,zone,invited_block_144,invited_block_108,recorded\nR1,Room 1,200,medium,Z,,,yes\nR2,Room 2,144,small,Z,,,no\nR3,Big,500,large,Z,,,no\n')
    open(os.path.join(d, 'schedule', 'slots.csv'), 'w').write(
        'slot_id,track,day,start,end,minutes,room_id\nMon-0800-R1,in_person,Mon,08:00,09:48,108,R1\nMon-0800-R2,in_person,Mon,08:00,09:48,108,R2\n')
    open(os.path.join(d, 'schedule', 'schedule.csv'), 'w').write('session_id,slot_id,locked\nA01,Mon-0800-R1,false\nA02,Mon-0800-R2,false\n')
    open(os.path.join(d, 'schedule', 'symposia.csv'), 'w').write(
        'session_id,title,minutes,day,start,end,room_id,block\nSYM-A,A Symposium,108,Mon,08:00,09:48,R3,X\n')
    note = tmp_path / 'note.html'
    note.write_text('<p>Please check <b>your</b> sessions.</p><script>x</script>')
    out = P.write(d, attendance=False)
    page = open(out, encoding='utf-8').read()
    out2 = P.write(d, out=str(tmp_path / 'review.html'), attendance=False, note=str(note), title='For review')
    page2 = open(out2, encoding='utf-8').read()
    d2 = json.loads(page2.split('<script type="application/json" id="data">')[1].split('</script>')[0])
    assert d2['note'].startswith('<p>Please check') and '<title>For review</title>' in page2 and page2.count('</script>') == 2
    data = json.loads(page.split('<script type="application/json" id="data">')[1].split('</script>')[0])
    assert out.endswith(os.path.join('views', 'schedule.html')) and '<title>DQI 2099 schedule</title>' in page
    assert {c['id'] for c in data['cells']} == {'A01', 'A02', 'SYM-A'}
    a01 = next(c for c in data['cells'] if c['id'] == 'A01')
    assert a01['room'] == 'R1' and a01['type'] == 'mini-symposium' and len(a01['talks']) == 3 and a01['talks'][1]['t'] == 'Talk  2'           # tags stripped from titles
    assert page.count('</script>') == 2
    assert data['room_desc']['R1'] == 'A 1 of 1: A 1' and data['room_desc']['R3'] == '1 DQI symposium'
    assert [r['rec'] for r in data['rooms']] == [True, False, False] and data['open'] == ['Mon|08:00|R1', 'Mon|08:00|R2', 'Mon|08:00|R3']


def test_strip_numbers_keeps_colour_drops_numbers():
    from dqi_sort import schedule_page as P
    data = {'rooms': [{'id': 'R1', 'cap': 100}],
            'cells': [{'id': 'A01', 'room': 'R1', 'est': 120, 'low': 80, 'high': 180, 'coh': 0.91, 'talks': [{'t': 'x', 'fit': 0.9}]},
                      {'id': 'A02', 'room': 'R1', 'est': 30, 'low': 20, 'high': 50, 'talks': []},
                      {'id': 'A03', 'room': 'R1', 'talks': []}]}
    P.strip_numbers(data)
    a, b, c = data['cells']
    assert a['heat'] == round((P.math.log(120) - P.math.log(P.LO)) / (P.math.log(P.HI) - P.math.log(P.LO)), 2) and a['over'] is True
    assert b['heat'] == 0.0 and 'over' not in b and 'heat' not in c
    assert not any(k in x for x in (a, b) for k in ('est', 'low', 'high', 'coh'))
    assert a['talks'][0]['fit'] is None
