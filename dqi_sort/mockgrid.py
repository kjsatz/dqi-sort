"""Make up a 2027-format venue and session grid (nothing in it is real): for a dry run, or as a stand-in until the real grid arrives.

    python -m dqi_sort.mockgrid DATA_DIR [--slack-min 126]
    python -m dqi_sort.mockgrid DATA_DIR --long 113 --short 94      provisional grid from APS's session counts

Sized to the in-person talks in talks.csv: Monday to Thursday four sessions a day (144, 108, 144, 108 minutes at
08:00, 11:00, 13:45, 16:45), Friday the first three. Rooms are added until the slots hold every talk minute plus
about one session of slack; the last room is open only for the slots needed. With --long and --short (the session
counts APS allots, before the real grid is known) rooms are added until there are exactly that many 144- and
108-minute slots. Half the rooms are small, a quarter medium and a quarter large (seats from config.yaml room_sizes).
Virtual slots: virtual_session_min (config) minutes, in the windows the virtual speakers listed (or the 2026 windows
if none), enough for every virtual talk plus spares.

Writes venue/rooms.csv, schedule/slots.csv, an empty schedule/schedule.csv and venue/README.md, and prints the
session_budget to put in config.yaml.
"""
import argparse, collections, csv, math, os, re
import yaml

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
BLOCKS = [('08:00', 144), ('11:00', 108), ('13:45', 144), ('16:45', 108)]   # the 2027 session times (APS symposia)
VIRTUAL_DEFAULT = ['05:30-07:30', '10:30-12:30', '15:30-17:30', '18:00-20:00']
ZONES = {'small': 'Hall A', 'medium': 'Hall B', 'large': 'Ballroom'}


def end(start, minutes):
    h, m = map(int, start.split(':'))
    t = h * 60 + m + minutes
    return f'{t // 60:02d}:{t % 60:02d}'


def week():
    return [(d, s, m) for d in DAYS for s, m in (BLOCKS[:3] if d == 'Fri' else BLOCKS)]


def make(data_dir, slack=126, n_long=None, n_short=None):
    with open(os.path.join(data_dir, 'config.yaml'), encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    seats = cfg.get('room_sizes') or {'small': 144, 'medium': 288, 'large': 500}
    with open(os.path.join(data_dir, 'talks.csv'), encoding='utf-8', newline='') as f:
        talks = [t for t in csv.DictReader(f) if t['status'] == 'active']
    need = sum(int(t['minutes']) for t in talks if t['track'] == 'in_person') + slack
    per_room = sum(m for _, _, m in week())
    counted = n_long is not None and n_short is not None
    if counted:                  # rooms until the slot counts are met; later rooms only for the slots still needed
        per = collections.Counter(m for _, _, m in week())
        n_rooms = max(math.ceil(n_long / per[144]), math.ceil(n_short / per[108]))
        rest = 0
    else:
        n_full = need // per_room
        rest = need - n_full * per_room
        n_rooms = n_full + (1 if rest else 0)
    counts = {'large': round(n_rooms / 4), 'medium': round(n_rooms / 4)}
    counts['small'] = n_rooms - counts['large'] - counts['medium']
    rooms, slots = [], []
    order = ['large'] * counts['large'] + ['medium'] * counts['medium'] + ['small'] * counts['small']
    idx = collections.Counter()
    for k, size in enumerate(order):
        idx[size] += 1
        rid = f"{size[0].upper()}{idx[size]}"
        rooms.append({'room_id': rid, 'name': f"{ZONES[size]} {idx[size]}", 'capacity': seats[size], 'size': size,
                      'zone': ZONES[size], 'invited_block_144': '', 'invited_block_108': ''})
        used = 0
        partial = k == len(order) - 1 and rest
        have = collections.Counter(x['minutes'] for x in slots)
        for d, s, m in week():
            if partial and used >= rest:
                break
            if counted and have[m] >= {144: n_long, 108: n_short}[m]:
                continue
            have[m] += 1
            slots.append({'slot_id': f"{d}-{s.replace(':', '')}-{rid}", 'track': 'in_person', 'day': d, 'start': s,
                          'end': end(s, m), 'minutes': m, 'room_id': rid})
            used += m
    wins = collections.Counter()
    for t in talks:
        if t['track'] == 'virtual':
            for w in re.findall(r'\d\d:\d\d-\d\d:\d\d', t['time_windows'] or ''):
                wins[w] += 1
    nv = sum(1 for t in talks if t['track'] == 'virtual')
    windows = [w for w, _ in wins.most_common()] or VIRTUAL_DEFAULT
    vmin = cfg.get('virtual_session_min') or 120
    vunits = sum(3 if t['type'] == 'invited' else 1 for t in talks if t['track'] == 'virtual')
    n_virtual = math.ceil(vunits / (vmin // 12)) + 4 if nv else 0
    for k in range(n_virtual):
        w = windows[k % len(windows)]
        d = DAYS[(k // len(windows)) % len(DAYS)]
        s, e = w.split('-')
        slots.append({'slot_id': f"{d}-{s.replace(':', '')}-VIRTUAL{k // (len(windows) * len(DAYS)) or ''}", 'track': 'virtual',
                      'day': d, 'start': s, 'end': end(s, vmin), 'minutes': vmin, 'room_id': ''})
    os.makedirs(os.path.join(data_dir, 'venue'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'schedule'), exist_ok=True)
    for path, cols, rows in [(('venue', 'rooms.csv'), list(rooms[0]), rooms), (('schedule', 'slots.csv'), list(slots[0]), slots),
                             (('schedule', 'schedule.csv'), ['session_id', 'slot_id', 'locked'], [])]:
        with open(os.path.join(data_dir, *path), 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, cols, lineterminator='\n'); w.writeheader(); w.writerows(rows)
    ip = [s for s in slots if s['track'] == 'in_person']
    c = collections.Counter(s['minutes'] for s in ip)
    by = collections.Counter(next(r['size'] for r in rooms if r['room_id'] == s['room_id']) for s in ip)
    why = (f"APS's session counts ({n_long} x 144 and {n_short} x 108 min) before the real grid is known: only the slot "
           f"counts are real; rooms and times are placeholders to be replaced by the real grid" if counted else
           "the sort to be tested on this year's abstracts")
    readme = f"""# Made-up venue

Nothing here is a real room or a real APS grid. It was generated by `python -m dqi_sort.mockgrid` in the 2027
format for {why}.

- Session times: Monday to Thursday {', '.join(f'{b} ({m} min)' for b, m in BLOCKS)}; Friday the first three.
- {len(rooms)} rooms, {len(ip)} in-person slots ({c[144]} x 144, {c[108]} x 108; {by['small']} small, {by['medium']} medium,
  {by['large']} large), {sum(s['minutes'] for s in ip)} minutes for {need - slack} minutes of talks.
- {n_virtual} virtual slots of {vmin} minutes in the windows the virtual speakers listed.
- Invited symposia are left out; `schedule/schedule.csv` is empty.
"""
    with open(os.path.join(data_dir, 'venue', 'README.md'), 'w', encoding='utf-8') as f:
        f.write(readme)
    print(readme)
    print(f'session_budget: {len(ip)}')
    return len(ip)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--slack-min', type=int, default=126)
    ap.add_argument('--long', type=int, help="number of 144-minute slots (APS's allotment); needs --short")
    ap.add_argument('--short', type=int, help='number of 108-minute slots; needs --long')
    a = ap.parse_args()
    if (a.long is None) != (a.short is None):
        ap.error('give both --long and --short, or neither')
    make(a.data_dir, a.slack_min, a.long, a.short)


if __name__ == '__main__':
    main()
