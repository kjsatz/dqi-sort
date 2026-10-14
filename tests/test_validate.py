import csv, os
import yaml
from dqi_sort import deliver, late, validate as V

TALK_COLS = ['talk_id', 'track', 'type', 'minutes', 'title', 'speaker', 'affiliation', 'institution', 'submitted_category', 'area',
             'series', 'series_part', 'time_windows', 'status', 'flags', 'notes']


def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(cols); w.writerows(rows)


def make(d):
    """A made-up year: two 108-minute sessions (one with an invited talk at block 2), a poster, an APS list."""
    cfg = {'session_budget': 2, 'max_same_institution': 4, 'talk_lengths_min': {'oral': 12, 'invited': 36},
           'aps_input': {'in_person': {'file': 'input/ip.csv'}},
           'aps_columns': {'ID': 'talk_id', 'First Name': 'first_name', 'Last Name': 'last_name', 'Affiliation': 'affiliation', 'SC': 'submitted_category',
                           'Type': 'type', 'Title': 'title', 'Body': 'body', 'Session Abbreviation': 'session_id', 'Speaking Order': 'order', 'Sorter Notes': 'sorter_note'},
           'aps_types': {'Oral': 'oral', 'Invited': 'invited'}, 'dqi_categories': {'17.01.01': 'Cats'}, 'areas': {'B': {}, 'A': {}}}
    (d / 'cards.jsonl').write_text(''); (d / 'abstracts.jsonl').write_text('')
    with open(d / 'config.yaml', 'w') as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    talks = [[f'{n}', 'in_person', 'oral', '12', f'Talk {n}', f'Speaker {n}', 'U', 'U', '17.01.01', 'A', '', '', '', 'active', '', ''] for n in range(1, 16)]
    talks[3] = ['4', 'in_person', 'invited', '36', 'Invited 4', 'Speaker 4', 'U', 'U', '17.01.01', 'A', '', '', '', 'active', '', '']
    talks[14][13] = 'poster'
    for k, t in enumerate(talks):                    # institutions spread out
        t[7] = t[6] = f'U{k % 5}'
    write(d / 'talks.csv', TALK_COLS, talks)
    write(d / 'input' / 'ip.csv', ['ID', 'First Name', 'Last Name', 'Affiliation', 'SC', 'Type', 'Title', 'Body', 'Session Abbreviation', 'Speaking Order', 'Sorter Notes'],
          [[t[0], 'Speaker', t[0], 'U', '17.01.01', 'Invited' if t[2] == 'invited' else 'Oral', t[4], 'body', '', '', ''] for t in talks])
    write(d / 'sorting' / 'sessions.csv', ['session_id', 'title', 'kind', 'minutes', 'size', 'area', 'locked', 'scope', 'notes'],
          [['A1', 'First', 'mini-symposium', '108', 'small', 'A', 'false', '', ''], ['B1', 'Second', 'contributed', '108', 'small', 'B', 'false', '', '']])
    a = [[str(n), 'A1', str(n), 'false', ''] for n in range(1, 8)] + [[str(n), 'B1', str(n - 7), 'false', ''] for n in range(8, 15)] + [['15', '', '', 'false', 'poster']]
    write(d / 'sorting' / 'assignments.csv', ['talk_id', 'session_id', 'order', 'locked', 'note'], a)
    write(d / 'sorting' / 'status_log.csv', ['when', 'talk_id', 'from_status', 'to_status', 'unit', 'by', 'note'],
          [['2026-10-01T10:00', '15', 'active', 'poster', '', 'lead', 'no science']])
    write(d / 'schedule' / 'slots.csv', ['slot_id', 'track', 'day', 'start', 'end', 'minutes', 'room_id'],
          [['Mon-0800-R1', 'in_person', 'Mon', '08:00', '09:48', '108', 'R1'], ['Mon-0800-R2', 'in_person', 'Mon', '08:00', '09:48', '108', 'R2']])
    write(d / 'schedule' / 'schedule.csv', ['session_id', 'slot_id', 'locked'], [['A1', 'Mon-0800-R1', 'false'], ['B1', 'Mon-0800-R2', 'false']])
    write(d / 'venue' / 'rooms.csv', ['room_id', 'name', 'capacity', 'size', 'zone', 'invited_block_144', 'invited_block_108'],
          [['R1', 'Room 1', '100', 'small', 'Z', '2', '2'], ['R2', 'Room 2', '100', 'small', 'Z', '1', '1']])
    write(d / 'chairs' / 'chairs.csv', ['area', 'name', 'email', 'affiliation', 'abstract_id', 'emailed', 'confirmed', 'availability', 'notes', 'session', 'check'],
          [['A', 'Chair One', 'c1@u', 'Uni One', '', 'TRUE', 'TRUE', '', '', 'A1', ''], ['B', 'Chair Two', 'c2@u', '', '', 'TRUE', 'TRUE', '', '', 'B1', '']])
    return d


def errors(d, delivery=False):
    probs, summary = V.validate(str(d), delivery, quiet=True)
    return [t for l, t in probs if l == 'ERROR'], summary


def test_clean_year_validates_and_reconciles(tmp_path):
    errs, s = errors(make(tmp_path), delivery=True)
    assert errs == []
    assert s['input'] == 15 and s['placed'] == 14 and [x[0] for x in s['omitted']] == ['15'] and s['added'] == []


def test_problems_are_found(tmp_path):
    d = make(tmp_path)
    rows = list(csv.reader(open(d / 'talks.csv')))
    rows[2][5] = 'Speaker 9'                          # talk 2 (A1) and talk 9 (B1): the same speaker at the same time
    rows[15][13] = 'withdrawn'                        # talk 15: withdrawn, but the log only knows poster
    write(d / 'talks.csv', rows[0], rows[1:])
    errs, _ = errors(d)
    assert any('speaks in A1 and B1' in e for e in errs)
    assert any('15: status withdrawn, but no decision' in e for e in errs)


def test_chair_who_speaks_in_their_session(tmp_path):
    d = make(tmp_path)
    rows = list(csv.reader(open(d / 'chairs' / 'chairs.csv')))
    rows[1][1] = 'Speaker 3'
    write(d / 'chairs' / 'chairs.csv', rows[0], rows[1:])
    assert any('speaks in A1, the session they chair' in e for e in errors(d)[0])


def test_late_withdraw_then_add_keeps_the_invited_block(tmp_path):
    d = make(tmp_path)
    late.withdraw(str(d), ['2'], do_commit=False)     # one talk fewer before the invited talk (block 2)
    assert any('invited talk 4 does not start a 36-minute block' in e for e in errors(d)[0])
    late.add(str(d), '99', to='A1', position=1, note='late submission', do_commit=False,
             fields={'title': 'Late', 'speaker': 'New Person', 'type': 'oral', 'track': 'in_person', 'category': '17.01.01'})
    errs, s = errors(d, delivery=True)
    assert errs == []
    assert [x[0] for x in s['added']] == ['99'] and sorted(x[0] for x in s['omitted']) == ['15', '2']


def test_unlogged_addition_is_an_error(tmp_path):
    d = make(tmp_path)
    late.add(str(d), '99', note='x', do_commit=False, fields={'title': 'Late', 'speaker': 'New', 'type': 'oral', 'track': 'in_person'})
    rows = [r for r in csv.reader(open(d / 'sorting' / 'status_log.csv')) if r[1] != '99']
    write(d / 'sorting' / 'status_log.csv', rows[0], rows[1:])
    late.move(str(d), '14', 'lonely', 'make room', do_commit=False)
    late.move(str(d), '99', 'B1', 'fill', do_commit=False)
    assert any('99: in a session but not in the APS input' in e for e in errors(d)[0])


def test_delivery_pages(tmp_path):
    d = make(tmp_path)
    pages = deliver.build(str(d))
    ip = pages['in_person']
    assert ip['header'][-3:] == ['Session Abbreviation', 'Speaking Order', 'Sorter Notes']
    assert [r[0] for r in ip['rows']][:8] == ['8', '9', '10', '11', '12', '13', '14', '1']      # areas in config order: B, then A
    assert ip['rows'][-1][0] == '15' and ip['rows'][-1][-3:] == ['', '', 'Poster']
    a1 = next(r for r in ip['sessions'] if r[0] == 'A1')
    assert a1[1:4] == [6, 1, 'Mon, 8:00 AM – 9:48 AM'] and a1[5:9] == ['Chair One', 'c1@u', 'Uni One', 'Confirmed'] and a1[-1] == 'Room 1'
    g = ip['grid']
    assert g['values'][g['head']][:3] == ['ID', 'First Name', 'Last Name'] and g['values'][1][g['s0']] == 'Session\nAbbreviation'
