"""Start next year's private data folder from this year's.

    python -m dqi_sort.new_year NEW_DIR --from OLD_DIR --year 2028

Makes NEW_DIR (it must not exist or be empty) as a git repo with one commit, holding:
- config.yaml: OLD_DIR's, with the settings that change every year blanked and marked "TODO (new year)" (meeting
  dates, division code, APS's sheet IDs, the Drive folder, invited_first, the session targets). Everything else
  (column map, units, areas, scheduling choices) carries over as a starting point; check it against APS's new sheet
  with `python -m dqi_sort.aps_input check NEW_DIR`.
- history/: OLD_DIR's attendance data, model and report, plus OLD_DIR's final program in history/<old year>/
  (sessions, schedule, rooms) for the refit once that year's RFID data arrives. input/attendance/ (raw exports) too.
- CLAUDE.md, open_questions.md, checkpoints.md, .gitignore: fresh, from templates.
It does not create the GitHub repo (the lead does, private, in the dqi-sorting organization; printed at the end).
Then follow RUNBOOK.md in dqi-sort from "Set up".
"""
import argparse, datetime, os, re, shutil, subprocess, sys
import yaml

RESET = {  # top-level key -> new value (YAML text), for settings that are always new each year
    'meeting_dates': '""',
    'division_code': '',
    'invited_first': '[]',
    'sheets': '{}',
}
TODO_KEYS = ['meeting_dates', 'division_code', 'dqi_categories', 'session_slots', 'session_budget', 'aps_sheet.id',
             'aps_sheet.snapshot_prefix', 'chair_volunteer_sheet.id', 'sheets (python -m dqi_sort.gsheets setup)',
             'room_sizes, size_cutoffs (once venue/rooms.csv is in)', 'invited_first (at talk order)']

CLAUDE_MD = """# DQI {year} (private data)

Private data repo for sorting and scheduling the DQI sessions of the {year} APS Global Physics Summit. The tools and the
process live in the public code repo, `../dqi-sort`: read its `RUNBOOK.md` (the steps, in order), `PROCESS.md` (why)
and `CLAUDE.md` first. Run `python -m dqi_sort.status .` (from dqi-sort: `.venv/bin/python -m dqi_sort.status ../THIS`)
to see where the run stands.

## Rules

- This repo holds conference data: unpublished abstracts and personal data. Never copy any of it into `../dqi-sort`
  or anywhere public, including plots or reports derived from it.
- Files follow the data format in `PROCESS.md`: plain CSV / JSONL, sorted by stable ID. Commit after every change with
  a message that says what moved and why.
- People decide at the checkpoints; log each in `checkpoints.md` in the lead's own words.
- Started on {today} from `{old}` by `python -m dqi_sort.new_year`.
"""
OPEN_Q = """# Open questions

What the lead could or should ask, grouped by whom to ask. None of it blocks the sort: each item has a working
assumption, and the sort goes ahead on it. When one is answered, tick it, add the answer and the date, and move it to
**Answered** at the end.

## Other units

## APS

## The chair

## Speakers

## Answered
"""
CHECKPOINTS = """# Checkpoints

The lead's decision at each checkpoint (PROCESS.md), in the lead's words, with the date and what was done.
"""


def reset_config(text):
    """OLD config text with the yearly settings blanked; still valid YAML."""
    for k, v in RESET.items():
        text = re.sub(rf'^{k}:.*$', f'{k}: {v}   # TODO (new year)', text, flags=re.M)
    text = re.sub(r'^(aps_sheet:.*\n(?:[ #].*\n)*?)  id: .*$', r'\1  id: ""   # TODO (new year): Google Sheet ID of the APS sorting sheet', text, flags=re.M)
    text = re.sub(r'^(chair_volunteer_sheet: \{.*?id: )[^,}]+', r'\1""', text, flags=re.M)
    return text


def year_of(cfg):
    m = re.findall(r'\d{4}', str(cfg.get('meeting_dates', '')))
    return m[-1] if m else 'previous'


def copy_tree(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))


def make(new, old, year):
    if os.path.exists(new) and os.listdir(new):
        sys.exit(f'{new} exists and is not empty')
    with open(os.path.join(old, 'config.yaml'), encoding='utf-8') as f:
        old_text = f.read()
    old_year = year_of(yaml.safe_load(old_text) or {})
    for sub in ('input/aps', 'input/chairs', 'input/attendance', 'venue', 'schedule', 'sorting', 'chairs', 'views', 'history'):
        os.makedirs(os.path.join(new, sub), exist_ok=True)
    head = ('# Config for the {y} DQI run, started from {o}\'s by `python -m dqi_sort.new_year` ({t}).\n'
            '# TODO (new year), before intake: ' + '; '.join(TODO_KEYS) + '.\n'
            '# Everything else is last year\'s choice: keep it unless APS\'s format or the lead says otherwise.\n'
            ).format(y=year, o=old_year, t=datetime.date.today().isoformat())
    text = head + reset_config(old_text)
    yaml.safe_load(text)                                 # still valid
    with open(os.path.join(new, 'config.yaml'), 'w', encoding='utf-8') as f:
        f.write(text)
    copy_tree(os.path.join(old, 'history'), os.path.join(new, 'history'))
    copy_tree(os.path.join(old, 'input', 'attendance'), os.path.join(new, 'input', 'attendance'))
    prog = os.path.join(new, 'history', str(old_year))
    os.makedirs(prog, exist_ok=True)
    for rel in ('sorting/sessions.csv', 'sorting/assignments.csv', 'schedule/schedule.csv', 'schedule/slots.csv', 'venue/rooms.csv'):
        src = os.path.join(old, rel)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(prog, os.path.basename(rel)))
    with open(os.path.join(prog, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(f'# The {old_year} program\n\nDQI\'s final {old_year} sessions, assignments, schedule and rooms, copied from `{old}`. '
                f'When the {old_year} RFID data arrives, match it to these sessions and add it to `history/attendance.csv`, then '
                f'refit (`python -m dqi_sort.attendance_report`; RUNBOOK.md, After the meeting).\n')
    files = {'CLAUDE.md': CLAUDE_MD.format(year=year, today=datetime.date.today().isoformat(), old=os.path.basename(os.path.abspath(old))),
             'open_questions.md': OPEN_Q, 'checkpoints.md': CHECKPOINTS,
             '.gitignore': '.DS_Store\n__pycache__/\nwork/\n'}
    for name, body in files.items():
        with open(os.path.join(new, name), 'w', encoding='utf-8') as f:
            f.write(body)
    for sub in ('input/aps', 'input/chairs', 'venue', 'schedule', 'sorting', 'chairs', 'views'):
        keep = os.path.join(new, sub, '.gitkeep')
        if not os.listdir(os.path.join(new, sub)):
            open(keep, 'w').close()
    subprocess.run(['git', 'init', '-q', '-b', 'main', new], check=True)
    subprocess.run(['git', '-C', new, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', new, 'commit', '-q', '-m', f'Start DQI {year} from {old_year} (python -m dqi_sort.new_year)'], check=True)
    name = os.path.basename(os.path.abspath(new))
    print(f'Made {new} (git, one commit). Next:\n'
          f'  1. Create the private GitHub repo (the lead): gh repo create dqi-sorting/{name} --private, then\n'
          f'     git -C {new} remote add origin <ssh url>; git -C {new} push -u origin main\n'
          f'  2. Fill the TODO (new year) settings in {new}/config.yaml\n'
          f'  3. Follow RUNBOOK.md from "Set up"; python -m dqi_sort.status {new} shows where you are')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('new_dir')
    ap.add_argument('--from', dest='old', required=True)
    ap.add_argument('--year', required=True)
    a = ap.parse_args()
    make(a.new_dir, a.old, a.year)


if __name__ == '__main__':
    main()
