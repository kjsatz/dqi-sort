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
