import csv, json, os, shutil, subprocess, sys
import pytest
from dqi_sort import textfix

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'aps_small')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_intake(d):
    r = subprocess.run([sys.executable, '-m', 'dqi_sort.intake', str(d)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout

def talks(d):
    return {r['talk_id']: r for r in csv.DictReader(open(os.path.join(d, 'talks.csv'), encoding='utf-8'))}

def abstracts(d):
    return {r['talk_id']: r for r in map(json.loads, open(os.path.join(d, 'abstracts.jsonl'), encoding='utf-8'))}


@pytest.fixture
def data(tmp_path):
    d = tmp_path / 'data'
    shutil.copytree(FIXTURE, d)
    return d


def test_textfix_repairs_only_damage():
    assert textfix.repair_encoding('Universit√§t') == 'Universität'
    assert textfix.repair_encoding('√É‚Ä∞cole') == 'École'
    assert textfix.repair_encoding('Many‚ÄëBody') == 'Many‑Body'
    for ok in ['x = √π + 1', 'Müller', '<em>a</em> &mu;s', '“quoted”', '≈ 5 µs']:
        assert textfix.repair_encoding(ok) == ok
    assert textfix.clean('A<!-- notionvc: x -->') == ('A', ['removed hidden HTML comments'])


def test_intake(data):
    run_intake(data)
    t, a = talks(data), abstracts(data)
    assert list(t) == sorted(t)
    assert len(t) == 7
    assert t['1000001']['type'] == 'invited' and t['1000001']['minutes'] == '36'
    assert t['1000003']['affiliation'] == 'Universität Musterstadt'
    assert t['1000001']['affiliation'] == 'École Fictive'
    assert t['1000002']['title'] == 'Fake title'
    assert 'category_not_dqi' in t['1000002']['flags']
    assert 'no_abstract' in t['1000001']['flags']
    assert 'same_abstract:1000005' in t['1000004']['flags']
    assert t['1000010']['track'] == 'virtual'
    assert t['1000010']['time_windows'] == '05:30-07:30 MDT;15:30-17:30 MDT'
    assert 'no_time_window' in t['1000011']['flags']
    assert all(r['status'] == 'active' for r in t.values())
    # minimal cleanup: markup that renders is left alone; raw kept for what changed
    assert a['1000003']['body'] == 'We study a <em>toy</em> model with &mu;s coherence and √π scaling.'
    assert a['1000003']['raw']['title'].startswith('Many‚Äë')
    assert a['1000002']['body'] == 'Infidelity below 10-5 for an imaginary gate.'
    assert 'raw' not in a['1000004']
    # session assignments go to reference/, not into talks.csv
    ref = list(csv.DictReader(open(data / 'reference' / 'aps_assignments.csv', encoding='utf-8')))
    assert ref == [{'talk_id': '1000001', 'session_id': 'TESTS1', 'order': '1', 'locked': '', 'note': 'keep first'}]


def test_rerun_keeps_later_work_and_never_drops_talks(data):
    run_intake(data)
    rows = list(csv.DictReader(open(data / 'talks.csv', encoding='utf-8')))
    for r in rows:
        if r['talk_id'] == '1000004':
            r.update(area='imaginary', institution='Nowhere Inst.', flags=r['flags'] + ';lead_checked')
    with open(data / 'talks.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, rows[0].keys(), lineterminator='\n'); w.writeheader(); w.writerows(rows)
    recs = abstracts(data)
    recs['1000003']['body'] = 'Hand-fixed body.'
    recs['1000003']['text_fix'].append({'field': 'body', 'fix': 'test', 'by': 'lead'})
    with open(data / 'abstracts.jsonl', 'w', encoding='utf-8') as f:
        f.writelines(json.dumps(recs[i], ensure_ascii=False) + '\n' for i in sorted(recs))
    # drop talk 1000005 from the APS input
    p = data / 'input' / 'in_person.csv'
    lines = [l for l in open(p, encoding='utf-8', newline='') if not l.startswith('1000005,')]
    open(p, 'w', encoding='utf-8', newline='').writelines(lines)

    out = run_intake(data)
    t = talks(data)
    assert len(t) == 7
    assert t['1000004']['area'] == 'imaginary' and t['1000004']['institution'] == 'Nowhere Inst.'
    assert 'lead_checked' in t['1000004']['flags'] and 'same_abstract' not in t['1000004']['flags']
    assert 'not_in_aps_input' in t['1000005']['flags']
    assert abstracts(data)['1000003']['body'] == 'Hand-fixed body.'
    assert 'Kept 1 hand-fixed' in out
