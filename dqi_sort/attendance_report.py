"""Write a short report on the attendance model, with figures.

    python -m dqi_sort.attendance_report DATA_DIR [--bootstrap 200]

Reads DATA_DIR/history/attendance.csv, refits the model (needs Ollama with embeddinggemma), and writes
DATA_DIR/history/attendance_report.md with attendance_report_check.png and attendance_report_effects.png.
Rerun it whenever attendance.csv gains a year.
"""
import argparse, datetime, math, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from dqi_sort import attendance as A

# categorical slots 1-3 of the reference palette (validated all-pairs for scatter); text in ink tokens
TYPE_COLOR = {'contributed': '#2a78d6', 'mini-symposium': '#eb6834', 'symposium': '#1baf7a'}
INK, INK2, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#8a8984', '#e4e3df', '#fcfcfb'
SLOT_START = {'morning': '08:00', 'midday': '12:00', 'afternoon': '15:30'}


def style():
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans'],
                         'font.size': 10, 'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                         'axes.edgecolor': MUTED, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE})


def tidy(ax, xgrid=True):
    ax.grid(axis='y', color=GRID, linewidth=0.8, zorder=0)
    if xgrid:
        ax.grid(axis='x', color=GRID, linewidth=0.8, zorder=0)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)


def holdout(rows, vec):
    """Fit on the earliest year, predict the latest. Returns per-session predictions and summary numbers."""
    years = sorted({r['year'] for r in rows})
    tr = [i for i, r in enumerate(rows) if r['year'] == years[0]]
    te = [i for i, r in enumerate(rows) if r['year'] == years[-1]]
    model = A.Model(A.fit_rows([rows[i] for i in tr], vec[tr]))
    test = [rows[i] for i in te]
    pred = model.interest([r['title'] for r in test], [r['type'] for r in test], vec[te])
    p = np.array([x['interest'] * model.slot_factor(r['day'], SLOT_START[r['block']]) for x, r in zip(pred, test)])
    a = np.array([r['peak'] for r in test], dtype=float)
    scale = float(np.median(a) / np.median(p))         # a new year's overall level is not known in advance
    p = p * scale
    s = model.m['sigma']
    inside = np.mean((a >= p * math.exp(-s)) & (a <= p * math.exp(s)))
    err = np.abs(np.log(p / a))
    return {'years': years, 'test': test, 'pred': p, 'actual': a, 'scale': scale, 'sigma': s,
            'rank': A._spearman(p, a), 'rank_type': A._spearman([model._base(r['type']) for r in test], a),
            'median_factor': math.exp(np.median(err)), 'within_1_5': float(np.mean(err < math.log(1.5))), 'inside_range': float(inside),
            'n_train': len(tr), 'n_test': len(te)}


def bootstrap(rows, vec, n, seed=0):
    """Refit on resampled sessions; returns arrays of type interest, day factors, time-of-day factors."""
    rng = np.random.default_rng(seed)
    out = {'type': [], 'day': [], 'block': []}
    for _ in range(n):
        idx = rng.integers(0, len(rows), len(rows))
        model = A.Model(A.fit_rows([rows[i] for i in idx], vec[idx], same=idx))
        out['type'].append([math.exp(model._base(t)) for t in A.TYPES])
        out['day'].append([model.slot_factor(d, '12:00') for d in A.DAYS])
        out['block'].append([model.slot_factor('Wed', SLOT_START[b]) for b in A.BLOCKS])
    return {k: np.array(v) for k, v in out.items()}


def figure_check(h, path, top=400):
    """Predicted vs actual on linear axes, equal scales; sessions above `top` sit on the edge with their value."""
    style()
    fig, ax = plt.subplots(figsize=(6.6, 6.9))
    L = top
    ax.fill_between([0, L], [0, L / 1.5], [0, L * 1.5], color=GRID, alpha=0.6, zorder=1, linewidth=0)
    ax.plot([0, L], [0, L], color=INK2, linewidth=1.2, zorder=2)
    edge = math.degrees(math.atan(1 / 1.5))             # the band's lower edge, y = x / 1.5
    ax.text(0.82 * L, 0.82 * L / 1.5, 'within a factor of 1.5', color=INK2, fontsize=9, ha='center', va='bottom',
            rotation=edge, rotation_mode='anchor', transform_rotates_text=True, zorder=2)
    ax.text(0.80 * L, 0.80 * L, 'predicted = actual', color=INK2, fontsize=9, ha='center', va='bottom',
            rotation=45, rotation_mode='anchor', transform_rotates_text=True, zorder=2)
    for t, col in TYPE_COLOR.items():
        for full in (False, True):
            k = [i for i, r in enumerate(h['test']) if r['type'] == t and r['censored'] == full]
            if not k:
                continue
            ax.scatter(h['pred'][k], np.minimum(h['actual'][k], L), s=46 if full else 34, marker='^' if full else 'o',
                       facecolor=SURFACE if full else col, edgecolor=col if full else SURFACE, linewidth=1.4 if full else 1,
                       alpha=0.9, zorder=3, clip_on=False, label=f'{t}' + (' (room full: demand was at least this)' if full else ''))
    for p_, a_ in zip(h['pred'], h['actual']):
        if a_ > L:                                      # off the chart: mark it on the top edge with its value
            ax.annotate(f'{a_:.0f} (off scale)', (p_, L), xytext=(7, -2), textcoords='offset points', fontsize=8.5, color=INK2, va='top')
    ax.set_xlim(0, L); ax.set_ylim(0, L); ax.set_aspect('equal')
    ax.set_xlabel(f"Predicted peak (model fitted on {h['years'][0]} only)")
    ax.set_ylabel(f"Actual {h['years'][-1]} RFID peak")
    ax.set_title(f"Predicting {h['years'][-1]} from {h['years'][0]}: {h['n_test']} sessions, one dot each", loc='left', fontsize=11, weight='bold', pad=10)
    ax.legend(frameon=False, loc='upper left', fontsize=8.5)
    ax.text(0.98, 0.03, f"rank correlation {h['rank']:.2f} (session type alone {h['rank_type']:.2f})\n"
            f"typical error ×{h['median_factor']:.2f}; within ×1.5 for {h['within_1_5']:.0%}",
            transform=ax.transAxes, ha='right', va='bottom', fontsize=9, color=INK2, linespacing=1.4)
    tidy(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_effects(model, boot, path):
    style()
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), gridspec_kw={'width_ratios': [3.6, 5, 3], 'wspace': 0.35})
    panels = [('Interest in an average slot', 'type', A.TYPES, [math.exp(model._base(t)) for t in A.TYPES], 'expected peak'),
              ('Day', 'day', A.DAYS, [model.slot_factor(d, '12:00') for d in A.DAYS], '× an average slot'),
              ('Time of day', 'block', A.BLOCKS, [model.slot_factor('Wed', SLOT_START[b]) for b in A.BLOCKS], '× an average slot')]
    for ax, (title, key, labels, est, ylab) in zip(axes, panels):
        lo, hi = np.percentile(boot[key], 5, axis=0), np.percentile(boot[key], 95, axis=0)
        x = np.arange(len(labels))
        col = [TYPE_COLOR[t] for t in labels] if key == 'type' else ['#2a78d6'] * len(labels)
        ax.vlines(x, lo, hi, color=col, linewidth=2, zorder=3)
        ax.scatter(x, est, s=60, color=col, edgecolor=SURFACE, linewidth=1.5, zorder=4)
        for xi, e in zip(x, est):
            ax.text(xi + 0.12, e, f'{e:.0f}' if key == 'type' else f'{e:.2f}', va='center', fontsize=9, color=INK2)
        if key != 'type':
            ax.axhline(1, color=MUTED, linewidth=1, linestyle=(0, (3, 3)), zorder=2)
            ax.set_ylim(0.55, 1.6)
        else:
            ax.set_ylim(0, max(hi) * 1.15)
        ax.set_xticks(x, [l.replace('mini-symposium', 'mini-\nsymposium') for l in labels])
        ax.set_xlim(-0.5, len(labels) - 0.3)
        ax.set_title(title, loc='left', fontsize=11, weight='bold', pad=8)
        ax.set_ylabel(ylab)
        tidy(ax, xgrid=False)
    fig.text(0.01, 0.01, 'Dots: fitted on all past sessions. Lines: 90% range from refitting on resampled sessions. '
             'Day and time factors size rooms only; they never decide which sessions get which slots.', fontsize=8, color=MUTED)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.24)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def topic_table(model, rows, n=8):
    """Past sessions with the highest and lowest slot-adjusted interest."""
    e = model.m['effects']
    year = np.mean([e[f'year:{y}'] for y in model.m['years']])
    adj = []
    for r, y in zip(rows, model.m['y']):
        slot = math.log(model.slot_factor(r['day'], SLOT_START[r['block']]))
        adj.append(math.exp(y - slot - e[f"year:{r['year']}"] + year))
    order = np.argsort(adj)
    line = lambda i: f"| {adj[i]:.0f} | {rows[i]['peak']}{'+' if rows[i]['censored'] else ''} | {rows[i]['type']} | {rows[i]['year']} {rows[i]['code']} | {rows[i]['title']} |"
    head = '| Interest | Peak | Type | Session | Title |\n|---|---|---|---|---|'
    return head + '\n' + '\n'.join(line(i) for i in order[::-1][:n]), head + '\n' + '\n'.join(line(i) for i in order[:n])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir'); ap.add_argument('--bootstrap', type=int, default=200)
    a = ap.parse_args()
    hist = os.path.join(a.data_dir, 'history')
    rows = A.read_history(a.data_dir)
    vec = A.ollama_embed([A.session_text(r['title'], r['type']) for r in rows])
    full = A.fit_rows(rows, vec)
    A.save(full, A.model_path(a.data_dir))
    model = A.Model(full)
    h = holdout(rows, vec)
    boot = bootstrap(rows, vec, a.bootstrap)
    figure_check(h, os.path.join(hist, 'attendance_report_check.png'))
    figure_effects(model, boot, os.path.join(hist, 'attendance_report_effects.png'))
    top, bottom = topic_table(model, rows)
    years = sorted({r['year'] for r in rows})
    day = {d: model.slot_factor(d, '12:00') for d in A.DAYS}
    base = {t: math.exp(model._base(t)) for t in A.TYPES}
    md = f"""# Attendance model report

Generated {datetime.date.today():%b %d, %Y} by `python -m dqi_sort.attendance_report` from `history/attendance.csv` ({len(rows)} sessions, {', '.join(years)}; {sum(r['censored'] for r in rows)} in full rooms). Method: `docs/attendance.md` in dqi-sort.

## In short

- For a proposed session, the model gives its **interest**: the expected RFID peak in an average slot, from its type and the most similar past session titles. Typical interest is {base['contributed']:.0f} for a contributed session, {base['mini-symposium']:.0f} for a mini-symposium and {base['symposium']:.0f} for a symposium.
- Interest does not depend on when a session runs. A separate **slot factor** (Monday ×{day['Mon']:.2f} … Friday ×{day['Fri']:.2f}) turns interest into the expected peak in a given slot, for sizing the room.
- Fitted on {h['years'][0]} alone, it ranked {h['years'][-1]}'s sessions with correlation {h['rank']:.2f}, against {h['rank_type']:.2f} for session type alone. Typical error is a factor of {h['median_factor']:.2f}; {h['inside_range']:.0%} of sessions fell inside the predicted range (meant to hold about 68%).
- Use it to rank sessions for the larger rooms, and size a room from the high end of the range when overflow would be costly. It does not know this year's hot topics; reviewers do.

## How well it predicts

![Predicted vs actual]({os.path.basename('attendance_report_check.png')})

Each dot is one {h['years'][-1]} session, predicted by a model that saw only {h['years'][0]} ({h['n_train']} sessions). Triangles are sessions whose room was full, so the actual demand was at least that high. {h['years'][-1]} drew ×{h['scale']:.2f} the level the model expected overall; a new year's level is unknown in advance, so this was applied before comparing.

## What it learned

![Effects]({os.path.basename('attendance_report_effects.png')})

The ranges are wide: two years of data cannot pin down a Friday or afternoon effect precisely, and part of any day effect reflects which sessions past sorters put there. The factors are shrunk toward "no effect" for that reason.

## Past sessions that drew the most, after adjusting for slot

{top}

## ...and the least

{bottom}

Interest = the session's peak, adjusted to an average slot and year. A "+" marks a full room (demand at least the peak).

## Using it

```
python -m dqi_sort.attendance predict DATA_DIR --title "Superconducting Qubit Readout" --type mini-symposium [--day Fri --start 08:00]
python -m dqi_sort.attendance predict DATA_DIR --sessions DATA_DIR/sorting/sessions.csv
```

Each line gives interest with a 68% range and the three past sessions it most resembles. In Python: `from dqi_sort import attendance; m = attendance.load(DATA_DIR)`, then `m.interest(titles, types, vectors)`, `m.slot_factor(day, start)` and `m.in_slot(interest, day, start)`. Ollama must be running with `embeddinggemma`.

Next year: add the new RFID export and room grid to `input/attendance/`, extend `history/build_attendance.py`, rebuild `history/attendance.csv`, then rerun this report (it refits and saves the model).

## Limits

- Two years, about {len(rows)} sessions. Both years had 180-minute sessions; 2027's are 144 or 108 minutes. Peak occupancy should carry over, but that is untested.
- Session titles only, by choice: talk lists would add a little, but "hot topic" context is missing either way.
- Time of day is three coarse blocks (morning, midday, afternoon).
"""
    with open(os.path.join(hist, 'attendance_report.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    print('wrote', os.path.join(hist, 'attendance_report.md'), 'and its two figures; refitted', A.model_path(a.data_dir))


if __name__ == '__main__':
    main()
