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
    out = P.write(d, attendance=False)
    page = open(out, encoding='utf-8').read()
    data = json.loads(page.split('<script type="application/json" id="data">')[1].split('</script>')[0])
    assert out.endswith(os.path.join('views', 'schedule.html')) and '<title>DQI 2099 schedule</title>' in page
    assert {c['id'] for c in data['cells']} == {'A01', 'A02', 'SYM-A'}
    a01 = next(c for c in data['cells'] if c['id'] == 'A01')
    assert a01['room'] == 'R1' and a01['type'] == 'mini-symposium' and len(a01['talks']) == 3 and a01['talks'][1]['t'] == 'Talk  2'           # tags stripped from titles
    assert page.count('</script>') == 2
    assert data['room_desc']['R1'] == 'A 1 of 1: A 1' and data['room_desc']['R3'] == '1 DQI symposium'
    assert [r['rec'] for r in data['rooms']] == [True, False, False] and data['open'] == ['Mon|08:00|R1', 'Mon|08:00|R2', 'Mon|08:00|R3']
