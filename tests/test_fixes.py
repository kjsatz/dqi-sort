import csv, json, pytest
from dqi_sort import fixes


def setup(tmp_path, rows):
    (tmp_path / 'abstracts.jsonl').write_text(json.dumps({'talk_id': '1000001', 'title': 'Imaginary fabricatio', 'body': 'Ada Example (MIT) We study nothing.',
                                                          'submitter_notes': ''}) + '\n')
    with open(tmp_path / 'talks.csv', 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n'); w.writerow(['talk_id', 'title']); w.writerow(['1000001', 'Imaginary fabricatio'])
    with open(tmp_path / 'fixes.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, ['talk_id', 'field', 'old', 'new', 'note'], lineterminator='\n'); w.writeheader(); w.writerows(rows)


def test_apply_keeps_raw_and_title(tmp_path):
    setup(tmp_path, [dict(talk_id='1000001', field='title', old='fabricatio', new='fabrication', note='complete cut-off word'),
                     dict(talk_id='1000001', field='body', old='Ada Example (MIT) ', new='', note='remove pasted author list')])
    assert fixes.apply(str(tmp_path), str(tmp_path / 'fixes.csv')) == ['1000001']
    r = json.loads((tmp_path / 'abstracts.jsonl').read_text())
    assert (r['title'], r['body']) == ('Imaginary fabrication', 'We study nothing.')
    assert r['raw']['body'].startswith('Ada') and r['text_fix'][0]['by'] == 'lead'
    assert 'Imaginary fabrication' in (tmp_path / 'talks.csv').read_text()


def test_apply_refuses_unmatched(tmp_path):
    setup(tmp_path, [dict(talk_id='1000001', field='body', old='not there', new='', note='')])
    with pytest.raises(SystemExit):
        fixes.apply(str(tmp_path), str(tmp_path / 'fixes.csv'))
