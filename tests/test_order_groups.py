import csv, os

from dqi_sort import order as O


def _talks(spec):
    return {i: {'talk_id': i, 'institution': inst} for i, inst in spec}


def test_group_splits_flags_only_split_institutions():
    talks = _talks([('1', 'Penn'), ('2', 'Penn'), ('3', 'HRL'), ('4', 'Sandia'), ('5', 'Penn'), ('6', 'Sandia'), ('7', '')])
    assert O.group_splits(['1', '2', '3', '4', '5', '6', '7'], talks) == ['Penn', 'Sandia']
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
        w.writerow({'round': 1, 'area': 'SPIN', 'reviewer': 'r', 'talk_id': '10', 'session_id': 'SPIN08', 'note': 'keep Penn block', 'resolution': ''})
        w.writerow({'round': 1, 'area': 'SPIN', 'reviewer': 'r', 'talk_id': '', 'session_id': 'SPIN08', 'note': 'session note', 'resolution': ''})
        w.writerow({'round': 1, 'area': 'SPIN', 'reviewer': 'r', 'talk_id': '11', 'session_id': 'SPIN08', 'note': 'done', 'resolution': 'moved'})
    by_talk, by_sess = O.reviewer_notes(str(tmp_path))
    assert by_talk == {'10': ['keep Penn block']}
    assert by_sess == {'SPIN08': ['session note']}


def test_reviewer_notes_missing_file(tmp_path):
    assert O.reviewer_notes(str(tmp_path)) == ({}, {})
