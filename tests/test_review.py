from dqi_sort import review as R


def test_diff_finds_moves_kicks_adds_orders_titles_and_notes():
    sent_sess = [{'session_id': 'A01', 'area': 'A', 'title': 'One', 'notes': ''}, {'session_id': 'A02', 'area': 'A', 'title': 'Two', 'notes': ''},
                 {'session_id': 'B01', 'area': 'B', 'title': 'Other', 'notes': ''}]
    sent = [{'talk_id': '1', 'session_id': 'A01', 'order': '1'}, {'talk_id': '2', 'session_id': 'A01', 'order': '2'},
            {'talk_id': '3', 'session_id': 'A02', 'order': '1'}, {'talk_id': '4', 'session_id': 'A02', 'order': '2'},
            {'talk_id': '5', 'session_id': 'A02', 'order': '3'}, {'talk_id': '9', 'session_id': 'B01', 'order': '1'}]
    rows = [{'Session': 'A01', 'Order': '2', 'Talk ID': '1', 'Move to lonely abstracts': 'FALSE', 'Notes': ''},
            {'Session': 'A01', 'Order': '1', 'Talk ID': '2', 'Move to lonely abstracts': 'FALSE', 'Notes': 'check part I'},
            {'Session': 'A01', 'Order': '3', 'Talk ID': '3', 'Move to lonely abstracts': 'FALSE', 'Notes': ''},
            {'Session': 'A02', 'Order': '1', 'Talk ID': '4', 'Move to lonely abstracts': 'TRUE', 'Notes': ''},
            {'Session': 'A02', 'Order': '2', 'Talk ID': '9', 'Move to lonely abstracts': 'FALSE', 'Notes': ''}]
    summary = [{'Session': 'A01', 'Title': 'One, Better', 'Room size override': 'large', 'Notes': ''},
               {'Session': 'A02', 'Title': 'Two', 'Room size override': '', 'Notes': 'needs a talk'}]
    ch = R.diff(sent, sent_sess, 'A', rows, summary)
    assert ch['moves'] == [{'talk': '3', 'from': 'A02', 'to': 'A01'}]
    assert ch['kicked'] == [{'talk': '4', 'from': 'A02'}]
    assert ch['added'] == [{'talk': '9', 'to': 'A02'}]                 # copied in from another area
    assert ch['missing'] == ['5']                                       # sent, not in the sheet, not ticked
    assert ch['orders']['A01'] == ['2', '1', '3']
    assert ch['titles'] == [{'session': 'A01', 'from': 'One', 'to': 'One, Better'}] and ch['sizes'] == [{'session': 'A01', 'size': 'large'}]
    assert {n['note'] for n in ch['notes']} == {'check part I', 'needs a talk'}


def test_renumber_keeps_the_given_order_then_the_rest():
    assign = {i: {'talk_id': i, 'session_id': 'S', 'order': o} for i, o in (('a', '1'), ('b', '2'), ('c', 999), ('d', 1.5))}
    R.renumber(assign, 'S')
    assert sorted(assign, key=lambda i: assign[i]['order']) == ['a', 'd', 'b', 'c']


def test_move_refuses_a_full_session(tmp_path):
    import csv, pytest
    d = tmp_path; (d / 'sorting').mkdir()
    with open(d / 'talks.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['talk_id', 'minutes', 'status'])
        w.writerows([[str(k), '12', 'active'] for k in range(1, 12)])
    with open(d / 'sorting' / 'sessions.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['session_id', 'minutes']); w.writerows([['A', '108'], ['B', '108']])
    with open(d / 'sorting' / 'assignments.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['talk_id', 'session_id', 'order', 'locked', 'note'])
        w.writerows([[str(k), 'A', str(k), 'false', ''] for k in range(1, 10)] + [['10', 'B', '1', 'false', ''], ['11', '', '', 'false', '']])
    with pytest.raises(SystemExit):
        R.move_one(str(d), '11', 'A', 'x')                 # A holds 9 x 12 = 108 already
    R.move_one(str(d), '11', 'B', 'x')
    assert any(r['talk_id'] == '11' and r['session_id'] == 'B' for r in csv.DictReader(open(d / 'sorting' / 'assignments.csv')))
