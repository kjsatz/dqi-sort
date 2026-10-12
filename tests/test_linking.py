import csv, pytest
from dqi_sort import linking as L


def test_title_parts():
    assert L.title_part('Imaginary devices (Part 2)') == 2
    assert L.title_part('Imaginary devices: Part II. Theory') == 2
    assert L.title_part('Imaginary devices - PART 1/2') == 1
    assert L.title_part('Imaginary devices') is None
    assert L.stem('Imaginary devices for nothing, Part I') == L.stem('Imaginary devices for nothing (part 2)')


def write(path, cols, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, cols, lineterminator='\n'); w.writeheader(); w.writerows(rows)


def setup(tmp_path, series):
    cols = ['talk_id', 'affiliation', 'institution', 'series', 'series_part', 'status', 'flags']
    write(tmp_path / 'talks.csv', cols, [dict(talk_id=i, affiliation='Nowhere Inst', institution='', series='', series_part='',
                                               status='active', flags='') for i in ('1000001', '1000002', '1000003')])
    write(tmp_path / 'institutions.csv', ['affiliation', 'institution'], [{'affiliation': 'Nowhere Inst', 'institution': 'Nowhere Institute'}])
    (tmp_path / 'linking').mkdir()
    write(tmp_path / 'linking' / 'series.csv', ['series_id', 'talk_id', 'part', 'sure', 'note'], series)


def test_apply_fills_series_and_institutions(tmp_path):
    setup(tmp_path, [dict(series_id='S001', talk_id='1000001', part=1, sure='no', note=''),
                     dict(series_id='S001', talk_id='1000002', part=2, sure='no', note='')])
    L.apply(str(tmp_path))
    t = {r['talk_id']: r for r in csv.DictReader(open(tmp_path / 'talks.csv'))}
    assert (t['1000002']['series'], t['1000002']['series_part']) == ('S001', '2')
    assert 'series_uncertain' in t['1000001']['flags'] and t['1000003']['series'] == ''
    assert t['1000003']['institution'] == 'Nowhere Institute'


def test_apply_refuses_bad_parts(tmp_path):
    setup(tmp_path, [dict(series_id='S001', talk_id='1000001', part=1, sure='yes', note=''),
                     dict(series_id='S001', talk_id='1000002', part=3, sure='yes', note='')])
    with pytest.raises(SystemExit):
        L.apply(str(tmp_path))
