import csv, math, random
import numpy as np
from dqi_sort import attendance as A

WORDS = ['qubit', 'sensing', 'foundations', 'readout', 'atoms', 'codes', 'materials', 'photonic']


def fake_embed(texts):
    """Bag-of-words vectors over a tiny vocabulary: enough to make similar titles similar."""
    v = np.array([[t.lower().count(w) for w in WORDS] + [0.3] for t in texts], dtype=float)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def make_history(tmp_path, n=160, seed=1):
    """Made-up sessions: 'qubit' titles draw 3x 'foundations' titles; Friday draws half as many."""
    rng = random.Random(seed)
    rows = []
    for k in range(n):
        topic = rng.choice(WORDS)
        day = rng.choice(A.DAYS)
        interest = {'qubit': 240, 'foundations': 80}.get(topic, 120)
        peak = interest * (0.5 if day == 'Fri' else 1.0) * math.exp(rng.gauss(0, 0.15))
        cap = 1000 if k % 7 else int(peak * 0.95)          # every 7th room was full
        peak = min(int(peak), cap) if k % 7 == 0 else int(peak)
        rows.append({'year': str(2025 + k % 2), 'session_code': f'MAR-{k}', 'title': f'Advances in {topic} {k}',
                     'type': 'contributed', 'type_as_given': '', 'primary_unit': 'DQI', 'day': day, 'start': '08:00',
                     'end': '11:00', 'minutes': '180', 'room': 'R', 'capacity': str(cap), 'peak': str(peak),
                     'entries': '', 'avg_visit_min': '', 'peak_share': '', 'full': '', 'note': ''})
    (tmp_path / 'history').mkdir()
    with open(tmp_path / 'history' / 'attendance.csv', 'w', newline='') as f:
        f.write('# made-up test data\n')
        w = csv.DictWriter(f, rows[0].keys(), lineterminator='\n'); w.writeheader(); w.writerows(rows)
    return tmp_path


def test_block():
    assert [A.block(s) for s in ('08:00', '10:45', '12:00', '15:30')] == ['morning', 'midday', 'midday', 'afternoon']


def test_fit_recovers_topic_and_friday(tmp_path):
    d = make_history(tmp_path)
    model = A.fit(str(d), embed=fake_embed)
    hot, cold = model.interest(['Advances in qubit'], ['contributed'], fake_embed(['contributed session: Advances in qubit']))[0], \
        model.interest(['Advances in foundations'], ['contributed'], fake_embed(['contributed session: Advances in foundations']))[0]
    assert hot['interest'] > 2 * cold['interest']
    assert hot['like'] and 'qubit' in hot['like'][0]
    assert model.slot_factor('Fri', '08:00') < 0.8 < model.slot_factor('Tue', '08:00')
    again = A.load(str(d))                                   # saved and reloaded
    assert again.slot_factor('Fri', '08:00') == model.slot_factor('Fri', '08:00')


def test_check_writes_report(tmp_path):
    d = make_history(tmp_path)
    report = A.check(str(d), embed=fake_embed)
    assert 'Rank correlation' in report and (d / 'history' / 'attendance_check.txt').exists()


def test_report_pieces_run(tmp_path):
    from dqi_sort import attendance_report as R
    d = make_history(tmp_path)
    rows = A.read_history(str(d))
    vec = fake_embed([A.session_text(r['title'], r['type']) for r in rows])
    h = R.holdout(rows, vec)
    assert -1 <= h['rank'] <= 1 and 0 <= h['inside_range'] <= 1
    boot = R.bootstrap(rows, vec, 3)
    model = A.Model(A.fit_rows(rows, vec))
    R.figure_check(h, str(tmp_path / 'c.png'))
    R.figure_effects(model, boot, str(tmp_path / 'e.png'))
    top, bottom = R.topic_table(model, rows)
    assert (tmp_path / 'c.png').exists() and 'qubit' in top and '| Interest |' in bottom


def test_size_suggestion():
    m = A.Model({'mu': 0, 'effects': {}, 'sigma': 0.4, 'years': []})
    sizes = {'small': 144, 'medium': 288, 'large': 500}
    assert m.size({'interest': 90, 'high': 130}, 'contributed', sizes) == ('small', '')
    assert m.size({'interest': 120, 'high': 180}, 'contributed', sizes) == ('small', 'may overflow')
    assert m.size({'interest': 140, 'high': 210}, 'mini-symposium', sizes) == ('medium', '')
    assert m.size({'interest': 60, 'high': 90}, 'symposium', sizes, symposium_min=200) == ('medium', '')
    assert m.size({'interest': 700, 'high': 900}, 'symposium', sizes) == ('large', 'larger than the largest class')
