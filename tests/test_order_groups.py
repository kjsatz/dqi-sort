import csv, os

from dqi_sort import order as O


def _talks(spec):
    return {i: {'talk_id': i, 'institution': inst} for i, inst in spec}


def test_group_splits_flags_only_split_institutions():
    talks = _talks([('1', 'Uni A'), ('2', 'Uni A'), ('3', 'Uni B'), ('4', 'Uni C'), ('5', 'Uni A'), ('6', 'Uni C'), ('7', '')])
    assert O.group_splits(['1', '2', '3', '4', '5', '6', '7'], talks) == ['Uni A', 'Uni C']
    assert O.group_splits(['1', '2', '5', '3', '4', '6', '7'], talks) == []


def test_group_splits_ignores_single_talks_and_blank_institutions():
    talks = _talks([('1', 'A'), ('2', ''), ('3', 'B'), ('4', '')])
    assert O.group_splits(['1', '2', '3', '4'], talks) == []


def test_reviewer_notes_skips_resolved(tmp_path):
    d = tmp_path / 'sorting'
    d.mkdir()
    with open(d / 'notes.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, ['round', 'area', 'reviewer', 'talk_id', 'session_id', 'note', 'resolution'])
        w.writeheader()
        w.writerow({'round': 1, 'area': 'XA', 'reviewer': 'r', 'talk_id': '10', 'session_id': 'X08', 'note': 'keep lab X block', 'resolution': ''})
        w.writerow({'round': 1, 'area': 'XA', 'reviewer': 'r', 'talk_id': '', 'session_id': 'X08', 'note': 'session note', 'resolution': ''})
        w.writerow({'round': 1, 'area': 'XA', 'reviewer': 'r', 'talk_id': '11', 'session_id': 'X08', 'note': 'done', 'resolution': 'moved'})
    by_talk, by_sess = O.reviewer_notes(str(tmp_path))
    assert by_talk == {'10': ['keep lab X block']}
    assert by_sess == {'X08': ['session note']}


def test_reviewer_notes_missing_file(tmp_path):
    assert O.reviewer_notes(str(tmp_path)) == ({}, {})


def test_group_runs_and_warnings_by_mode():
    talks = _talks([('1', 'G'), ('2', 'G'), ('3', 'G'), ('4', 'U'), ('5', 'U'), ('6', 'G')])
    order = ['1', '2', '3', '4', '5', '6']
    assert O.group_runs(order, talks) == ['G']
    assert O.institution_warnings(order, talks, 'group') == ['talks from G are not together']
    assert O.institution_warnings(order, talks, 'mix') == ['more than two talks in a row from G']
    assert O.institution_warnings(order, talks, 'none') == []


def test_institution_order_config():
    from dqi_sort import sessions as S
    assert S.institution_order({})[0] == 'group'
    assert S.institution_order({'institution_order': 'Mix'})[0] == 'mix'
    assert S.institution_order({'institution_order': 'none'}) == ('none', '')
    import pytest
    with pytest.raises(SystemExit):
        S.institution_order({'institution_order': 'cluster'})


def test_card_text_shows_also_presenting():
    from dqi_sort import sessions as S
    t = {'talk_id': '1', 'type': 'oral', 'title': 'T', 'speaker': 'S', 'institution': 'I', 'affiliation': 'I',
         'series': '', 'series_part': '', 'track': 'in_person', 'time_windows': '', 'flags': '',
         'also_presenting': 'Invited symposium X (Mon 8:00)'}
    assert 'speaker also presents: Invited symposium X (Mon 8:00)' in S.card_text(t, None, {})


def test_invited_first_overrides_the_rooms_block():
    talks = {'i': {'type': 'invited', 'minutes': '36', 'series': '', 'series_part': ''}}
    talks.update({str(n): {'type': 'oral', 'minutes': '12', 'series': '', 'series_part': ''} for n in range(6)})
    members = {'S1': ['i'] + [str(n) for n in range(6)]}
    sched = {'S1': {'room_id': 'R', 'minutes': '108', 'day': 'Mon', 'start': '08:00'}}
    rooms = {'R': {'invited_block_108': '3'}}
    assert O.target_block('S1', members, talks, sched, rooms)[1] == 3
    assert O.target_block('S1', members, talks, sched, rooms, frozenset({'S1'})) == (1, 1)
    first_order = members['S1']
    assert O.session_problems('S1', first_order, talks, sched, rooms, members, frozenset({'S1'})) == []
    assert O.session_problems('S1', first_order, talks, sched, rooms, members)       # block 3 wanted by the room
