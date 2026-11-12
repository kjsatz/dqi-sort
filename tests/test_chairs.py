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
    entries = {('A', 'Ada', 'ada@u'): {'area': 'A', 'name': 'Ada', 'email': 'ada@u', 'confirmed': 'TRUE', 'availability': 'Tue', 'session': ''}}
    C.place(entries, vols, sess, sched, {}, {}, busy, '.')
    assert entries[('A', 'Ada', 'ada@u')]['session'] == ''      # presents Monday 08:00, unavailable Tuesday: nowhere to go
    entries[('A', 'Ada', 'ada@u')]['availability'] = ''
    C.place(entries, vols, sess, sched, {}, {}, busy, '.')
    assert entries[('A', 'Ada', 'ada@u')]['session'] == 'A3'


def test_checks_flag_a_chair_who_presents_then():
    sess = {'A1': {'area': 'A'}}
    sched = {'A1': {'day': 'Mon', 'start': '08:00'}}
    entries = {('A', 'Bo', 'bo@u'): {'area': 'A', 'name': 'Bo', 'email': 'bo@u', 'confirmed': 'TRUE', 'session': 'A1'}}
    C.checks(entries, [], sess, sched, {'bo@u': {('Mon', '08:00')}})
    assert entries[('A', 'Bo', 'bo@u')]['check'] == 'A1: presents at this time'


def test_a_chair_may_chair_two_sessions():
    sess = {'A1': {'area': 'A'}, 'A2': {'area': 'A'}, 'A3': {'area': 'A'}}
    sched = {'A1': {'day': 'Mon', 'start': '08:00'}, 'A2': {'day': 'Mon', 'start': '08:00'}, 'A3': {'day': 'Tue', 'start': '08:00'}}
    e = {'area': 'A', 'name': 'Cy', 'email': 'cy@u', 'confirmed': 'TRUE', 'session': 'a1; A3'}
    assert C.codes(e) == ['A1', 'A3']
    entries = {('A', 'Cy', 'cy@u'): e, ('A', 'Di', 'di@u'): {'area': 'A', 'name': 'Di', 'email': 'di@u', 'confirmed': 'TRUE', 'session': ''}}
    C.place(entries, [], sess, sched, {}, {}, {}, '.')
    assert entries[('A', 'Di', 'di@u')]['session'] == 'A2'          # A1 and A3 are taken by Cy
    e['session'] = 'A1; A2'
    C.checks(entries, [], sess, sched, {})
    assert 'chairs two sessions at this time' in e['check']


def test_instructions_for_aps_invites_and_chosen_flag(tmp_path):
    from dqi_sort import chairs as C
    how = C.instructions({'chair_process': 'aps_invites'})
    text = ' '.join(' '.join(r) for r in how)
    assert 'APS will send the chair invitations' in text and 'Subject:' not in text and 'diverse' in text and 'Emailed?' not in text
    assert 'Subject:' in ' '.join(' '.join(r) for r in C.instructions({}))
    d = tmp_path; (d / 'v.csv').write_text('Sub-category,First name,Email,Affiliation,Chairing method,Abstract ID,Chosen,APS notes\n'
                                           '24.01.01,Ada,ada@x.org,X,Both,100,TRUE,DQI VIRTUAL01 chair\n'
                                           '24.01.01,Bo,bo@x.org,Y,In-person,101,FALSE,\n', encoding='utf-8')
    vols = C.volunteers(str(d), {'chair_volunteers': {'in_person': 'v.csv'}, 'division_code': 24}, {})
    notes = {v['name']: v['match_note'] for v in vols}
    assert 'already chosen' in notes['Ada'] and 'VIRTUAL01' in notes['Ada'] and 'already chosen' not in notes['Bo']


def test_assign_only_layout_drops_checkboxes_and_moves_session():
    from dqi_sort import chairs as C
    cols, edit, boxes, chosen, count = C.layout({'chair_process': 'aps_invites'})
    assert 'Emailed?' not in cols and 'Confirmed?' not in cols and boxes == []
    assert cols.index('Chairing session(s)') < cols.index('Availability') < cols.index('Notes')
    assert chosen == 'ABCDEFGHIJ'[cols.index('Chairing session(s)')] and count == 'COUNTA'
    vols = [{'name': 'Ada', 'email': 'ada@x.org', 'affiliation': 'X', 'talk_ids': '1', 'own_sessions': 'S01', 'match_note': '', 'area': 'A'}]
    rows, n = C.area_rows('A', vols, {('A', 'Ada', 'ada@x.org'): {'session': 'S02', 'notes': 'n'}}, {}, {}, cols=cols)
    assert n == 1 and rows[0][cols.index('Chairing session(s)')] == 'S02' and len(rows[0]) == len(cols)
    assert C.layout({})[0] == C.COLS
