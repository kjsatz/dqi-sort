import json
from dqi_sort import cards

CFG = {'dqi_categories': {'17.01.01': 'Test A', '17.01.02': 'Test B'}, 'other_units': {'DAMOP': 'Atomic'}}


def card(**kw):
    c = {'talk_id': '1000001', 'platform': 'made-up qubit', 'problem': 'imaginary loss', 'approach': 'experiment',
         'key_claim': 'We did a made-up thing.', 'keywords': ['alpha', 'beta', 'gamma'], 'best_category': '17.01.01',
         'runner_up_category': None, 'session_pitch': 'Imaginary devices', 'affiliation': 'Nowhere Institute',
         'multi_part': None, 'constraints': None, 'leadership_review': None, 'promotional': None, 'other_unit': None, 'malformed': None}
    c.update(kw)
    return c


def test_valid_card():
    assert cards.problems(card(), CFG) == []


def test_bad_cards():
    assert cards.problems(card(approach='vibes'), CFG)
    assert cards.problems(card(keywords=['one']), CFG)
    assert cards.problems(card(best_category='99.99.99'), CFG)
    assert cards.problems(card(other_unit={'unit': 'DAMOP', 'strength': 'maybe', 'reason': 'x'}), CFG)
    c = card(); del c['malformed']
    assert cards.problems(c, CFG)


def test_check_batch_matches_input(tmp_path):
    batch = [{'talk_id': '1000001', 'type': 'oral', 'title': 'T', 'body': 'B', 'submitter_notes': '', 'affiliation': 'Nowhere Institute'},
             {'talk_id': '1000002', 'type': 'oral', 'title': 'T2', 'body': 'B2', 'submitter_notes': '', 'affiliation': 'Elsewhere'}]
    (tmp_path / 'batch_000.json').write_text(json.dumps(batch))
    out = tmp_path / 'batch_000.out.json'
    out.write_text(json.dumps([card()]))                                        # one card missing
    assert cards.check_batch(str(out), CFG)[1]
    out.write_text(json.dumps([card(), card(talk_id='1000002', affiliation='Elsewhere')]))
    assert cards.check_batch(str(out), CFG)[1] == []
    out.write_text(json.dumps([card(), card(talk_id='1000002', affiliation='Somewhere else')]))
    assert any('affiliation' in e for e in cards.check_batch(str(out), CFG)[1])


def test_prepare_refuses_with_unmerged_outputs(tmp_path):
    import pytest
    w = tmp_path / 'work' / 'cards'; w.mkdir(parents=True)
    (w / 'batch_000.out.json').write_text('[]')
    (tmp_path / 'config.yaml').write_text('dqi_categories: {}\n')
    (tmp_path / 'abstracts.jsonl').write_text('')
    (tmp_path / 'talks.csv').write_text('talk_id,type,affiliation,status\n')
    with pytest.raises(SystemExit):
        cards.prepare(str(tmp_path), None, 100)
    assert (w / 'batch_000.out.json').exists()
