import csv
from dqi_sort import chairs as C


def test_volunteers_merge_by_email_link_by_id_and_name(tmp_path):
    d = tmp_path
    head = ['Sub-Category', 'Chairing Method\n(in-person vs virtual)', "Speaker's Presentation Method", 'First Name', 'Last Name',
            'Affiliation', 'Email', 'ID', 'Have you session chaired before?']
    with open(d / 'ip.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(head)
        w.writerow(['17.01.01', 'In-person', 'In-person', 'Ada', 'Lovelace', 'U', 'ada@u.edu', '1', 'Yes'])
        w.writerow(['06.01.01', 'In-person', 'In-person', 'Not', 'Ours', 'U', 'x@u.edu', '9', 'No'])       # another division
    with open(d / 'v.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(head)
        w.writerow(['17.02.01', 'Both', 'In-person', 'Ada', 'Lovelace', 'U', 'ADA@u.edu', '1', 'Yes'])      # same person
    talks = {'1': {'talk_id': '1', 'speaker': 'Ada Lovelace', 'status': 'active'},
             '2': {'talk_id': '2', 'speaker': 'Ada Lovelace', 'status': 'active'}}
    v = C.volunteers(str(d), {'division_code': '17', 'chair_volunteers': {'in_person': 'ip.csv', 'virtual': 'v.csv'}}, talks)
    assert len(v) == 1 and v[0]['chair_mode'] == 'both' and v[0]['talk_ids'] == '1;2' and 'by name' in v[0]['match_note']


def test_availability_free_text():
    assert C.unavailable('Mon AM; Thu', 'Mon', '08:00') and not C.unavailable('Mon AM; Thu', 'Mon', '13:30')
    assert C.unavailable('Mon AM; Thu', 'Thu', '16:15') and not C.unavailable('', 'Fri', '08:00')
    assert C.unavailable('not Thursday afternoon', 'Thu', '13:30') and not C.unavailable('not Thursday afternoon', 'Thu', '10:45')
    assert C.reading('Mon AM; not Thursday afternoon; Fri') == 'read as unavailable: Mon AM, Thu PM, Fri'


def test_place_avoids_own_session_and_talk_time():
    sess = {'A1': {'area': 'A'}, 'A2': {'area': 'A'}, 'A3': {'area': 'A'}}
    sched = {'A1': {'day': 'Mon', 'start': '08:00'}, 'A2': {'day': 'Mon', 'start': '08:00'}, 'A3': {'day': 'Tue', 'start': '08:00'}}
    vols = [{'name': 'Ada', 'email': 'ada@u', 'talk_ids': ''}]
    busy = {'ada@u': {('Mon', '08:00')}}
    entries = {('A', 'Ada', 'ada@u'): {'area': 'A', 'name': 'Ada', 'email': 'ada@u', 'status': 'confirmed', 'availability': 'Tue', 'session': ''}}
    C.place(entries, vols, sess, sched, {}, {}, busy, '.')
    assert entries[('A', 'Ada', 'ada@u')]['session'] == ''      # presents Monday 08:00, unavailable Tuesday: nowhere to go
    entries[('A', 'Ada', 'ada@u')]['availability'] = ''
    C.place(entries, vols, sess, sched, {}, {}, busy, '.')
    assert entries[('A', 'Ada', 'ada@u')]['session'] == 'A3'


def test_checks_flag_a_chair_who_presents_then():
    sess = {'A1': {'area': 'A'}}
    sched = {'A1': {'day': 'Mon', 'start': '08:00'}}
    entries = {('A', 'Bo', 'bo@u'): {'area': 'A', 'name': 'Bo', 'email': 'bo@u', 'status': 'confirmed', 'session': 'A1'}}
    C.checks(entries, [], sess, sched, {'bo@u': {('Mon', '08:00')}})
    assert entries[('A', 'Bo', 'bo@u')]['check'] == 'presents at this time'
