"""Session attendance model: how many people a proposed session will draw.

    python -m dqi_sort.attendance fit DATA_DIR
    python -m dqi_sort.attendance check DATA_DIR
    python -m dqi_sort.attendance predict DATA_DIR --title "Superconducting qubit readout" --type contributed [--day Fri --start 08:00]
    python -m dqi_sort.attendance predict DATA_DIR --sessions DATA_DIR/sorting/sessions.csv

Data: DATA_DIR/history/attendance.csv (one row per past session; see docs/attendance.md). The model is

    log(peak) = interest + slot effect (day, time of day) + year effect + noise

    interest  = session-type effect + title term

The title term is the average of the most similar past sessions (EmbeddingGemma embedding of
"<type> session: <title>"), after their own slot and year effects are removed. A session whose
peak reached 90% of its room's capacity only tells us demand was at least that high; the fit
treats it as censored. Slot and type effects are shrunk toward zero (no effect) unless the data
clearly supports them.

`interest` is a session's expected peak in an average slot. It is what to use when comparing
proposed sessions; it does not depend on when a session is scheduled. `in_slot` multiplies in a
slot's effect, for sizing the room once the session has a slot.

fit writes DATA_DIR/history/attendance_model.npz. check fits on the earliest year only and predicts
the latest, and writes the result to DATA_DIR/history/attendance_check.txt.
"""
import argparse, csv, json, math, os, sys
import numpy as np

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
BLOCKS = ['morning', 'midday', 'afternoon']
TYPES = ['contributed', 'mini-symposium', 'symposium']
K_NEIGHBOURS = 10      # past sessions averaged for the title term
TEMPERATURE = 0.05     # softmax width over cosine similarity of those neighbours
SHRINK = 10.0          # ridge penalty on type/slot/year effects, in pseudo-sessions of "no effect"
FULL_AT = 0.9          # peak at this share of capacity or more: demand is at least the peak


def block(start):
    """Time of day of a session start ("08:00", "15:30") as morning / midday / afternoon."""
    h, m = map(int, start.split(':'))
    t = h + m / 60
    return 'morning' if t < 10.5 else 'midday' if t < 14 else 'afternoon'


def session_text(title, typ):
    return f'{typ} session: {title}'


def ollama_embed(texts):
    from dqi_sort.embed import run_ollama
    v = run_ollama(texts)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# ---------- data ----------
def read_history(data_dir):
    path = os.path.join(data_dir, 'history', 'attendance.csv')
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(l for l in f if not l.startswith('#'))]
    out = []
    for r in rows:
        if r['type'] not in TYPES or not r['peak'] or int(r['peak']) <= 0:
            continue
        cap = int(r['capacity']) if r['capacity'] else None
        out.append({'year': r['year'], 'code': r['session_code'], 'title': r['title'], 'type': r['type'],
                    'day': r['day'], 'block': block(r['start']), 'peak': int(r['peak']),
                    'censored': bool(cap and int(r['peak']) >= FULL_AT * cap)})
    return out


# ---------- model ----------
def _design(rows, years):
    """One-hot columns for type, year, day, time of day (intercept handled separately)."""
    cols = [('type', t) for t in TYPES] + [('year', y) for y in years] + [('day', d) for d in DAYS] + [('block', b) for b in BLOCKS]
    X = np.zeros((len(rows), len(cols)))
    for i, r in enumerate(rows):
        for j, (k, v) in enumerate(cols):
            X[i, j] = float(r.get(k) == v)
    return X, cols


def _neighbour_weights(sim, k=K_NEIGHBOURS):
    """Softmax weights over the k most similar columns of each row of sim (others get 0)."""
    w = np.zeros_like(sim)
    idx = np.argsort(-sim, axis=1)[:, :k]
    for i, js in enumerate(idx):
        e = np.exp((sim[i, js] - sim[i, js].max()) / TEMPERATURE)
        w[i, js] = e / e.sum()
    return w


def _spearman(x, y):
    """Rank correlation, with tied values sharing their average rank."""
    def ranks(v):
        v = np.asarray(v, dtype=float)
        order = np.argsort(v, kind='mergesort')
        r = np.empty(len(v))
        r[order] = np.arange(len(v))
        for u in np.unique(v):
            r[v == u] = r[v == u].mean()
        return r
    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def _phi(z):
    return math.exp(-z * z / 2) / math.sqrt(2 * math.pi)


def _Phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def fit_rows(rows, vectors, iterations=40, same=None):
    """Fit the model to past sessions; returns a dict of arrays and effects.

    same: optional label per row; rows with equal labels are never each other's neighbours
    (used when resampling, where a session can appear more than once)."""
    years = sorted({r['year'] for r in rows})
    X, cols = _design(rows, years)
    y_obs = np.log([r['peak'] for r in rows])
    cens = np.array([r['censored'] for r in rows])
    sim = vectors @ vectors.T
    np.fill_diagonal(sim, -np.inf)                      # a session is not its own neighbour
    if same is not None:
        same = np.asarray(same)
        sim[same[:, None] == same[None, :]] = -np.inf
    W = _neighbour_weights(sim)
    y = y_obs.copy()
    title = np.zeros(len(rows))
    for _ in range(iterations):
        target = y - title
        mu = target.mean()
        A = X.T @ X + SHRINK * np.eye(X.shape[1])
        beta = np.linalg.solve(A, X.T @ (target - mu))
        fixed = mu + X @ beta
        r = y - fixed                                    # what the title has to explain
        mu += r.mean()                                   # keep the title term centred on zero, so the
        fixed += r.mean()                                # overall level lives in mu, not in the titles
        r -= r.mean()
        title = W @ r
        resid = y - fixed - title
        sigma = max(float(resid.std()), 0.05)
        m = fixed + title
        for i in np.where(cens)[0]:                      # E[y | y >= observed] for full rooms
            z = (y_obs[i] - m[i]) / sigma
            y[i] = m[i] + sigma * _phi(z) / max(1 - _Phi(z), 1e-9)
    eff = {f'{k}:{v}': float(b) for (k, v), b in zip(cols, beta)}
    return {'mu': float(mu), 'effects': eff, 'sigma': sigma, 'years': years, 'y': y, 'fitted': fixed + title,
            'r': r, 'vectors': vectors, 'titles': [r_['title'] for r_ in rows],
            'codes': [f"{r_['year']} {r_['code']}" for r_ in rows], 'types': [r_['type'] for r_ in rows]}


class Model:
    def __init__(self, m):
        self.m = m

    def _base(self, typ):
        e = self.m['effects']
        year = np.mean([e[f'year:{y}'] for y in self.m['years']])     # a new year: the past years' average
        return self.m['mu'] + e[f'type:{typ}'] + year

    def interest(self, titles, types, vectors):
        """Expected peak in an average slot, a 68% range, and the past sessions behind each estimate."""
        sim = vectors @ self.m['vectors'].T
        W = _neighbour_weights(sim)
        title = W @ self.m['r']
        out = []
        for i, (t, typ) in enumerate(zip(titles, types)):
            log_mid = self._base(typ) + title[i]
            near = np.argsort(-W[i])[:3]
            out.append({'title': t, 'type': typ, 'interest': round(math.exp(log_mid)),
                        'low': round(math.exp(log_mid - self.m['sigma'])), 'high': round(math.exp(log_mid + self.m['sigma'])),
                        'like': [self.m['codes'][j] + ' ' + self.m['titles'][j] for j in near if W[i, j] > 0.05]})
        return out

    def size(self, estimate, typ, cutoffs, seats=None, symposium_min=0):
        """Suggested room size class for one estimate from interest(): (class, note).

        cutoffs: {class: lowest estimated peak for that class}, e.g. {small: 0, medium: 90, large: 180}; set low on
        purpose, as a starting point for people to adjust. seats: {class: seats per room}. Symposia get at least
        a class with `symposium_min` seats. The note warns when the high end of the range exceeds the room."""
        order = sorted(cutoffs, key=lambda c: cutoffs[c])
        cls = [c for c in order if estimate['interest'] >= cutoffs[c]][-1:] or order[:1]
        cls = cls[0]
        if typ == 'symposium' and seats and seats.get(cls, 0) < symposium_min:
            cls = next((c for c in order if seats.get(c, 0) >= symposium_min), order[-1])
        note = 'may overflow' if seats and estimate['high'] > seats.get(cls, float('inf')) else ''
        return cls, note

    def slot_factor(self, day, start):
        """How much a slot scales attendance relative to an average slot."""
        e = self.m['effects']
        days = np.mean([e[f'day:{d}'] for d in DAYS])
        blocks = np.mean([e[f'block:{b}'] for b in BLOCKS])
        return math.exp(e.get(f'day:{day}', days) - days + e.get(f'block:{block(start)}', blocks) - blocks)

    def in_slot(self, interest, day, start):
        return round(interest * self.slot_factor(day, start))


# ---------- save / load ----------
def model_path(data_dir):
    return os.path.join(data_dir, 'history', 'attendance_model.npz')


def save(m, path):
    meta = {k: m[k] for k in ('mu', 'effects', 'sigma', 'years', 'titles', 'codes', 'types')}
    meta['settings'] = {'k': K_NEIGHBOURS, 'temperature': TEMPERATURE, 'shrink': SHRINK, 'full_at': FULL_AT}
    np.savez_compressed(path, r=m['r'], vectors=m['vectors'].astype(np.float16), meta=np.array(json.dumps(meta)))


def load(data_dir):
    z = np.load(model_path(data_dir), allow_pickle=False)
    m = json.loads(str(z['meta']))
    m['r'], m['vectors'] = z['r'], z['vectors'].astype(np.float32)
    return Model(m)


# ---------- commands ----------
def fit(data_dir, embed=ollama_embed):
    rows = read_history(data_dir)
    m = fit_rows(rows, embed([session_text(r['title'], r['type']) for r in rows]))
    save(m, model_path(data_dir))
    model = Model(m)
    print(f"fitted on {len(rows)} sessions ({sum(r['censored'] for r in rows)} at capacity); "
          f"typical error factor x{math.exp(m['sigma']):.2f}")
    print('type, in an average slot:', {t: round(math.exp(model._base(t))) for t in TYPES})
    print('slot factors:', {d: round(model.slot_factor(d, '12:00'), 2) for d in DAYS},
          {b: round(model.slot_factor('Wed', s), 2) for b, s in zip(BLOCKS, ['08:00', '12:00', '15:30'])})
    print('wrote', model_path(data_dir))
    return model


def check(data_dir, embed=ollama_embed):
    """Fit on the earliest year, predict the latest; report how useful the predictions are."""
    rows = read_history(data_dir)
    years = sorted({r['year'] for r in rows})
    train = [r for r in rows if r['year'] == years[0]]
    test = [r for r in rows if r['year'] == years[-1]]
    vec = embed([session_text(r['title'], r['type']) for r in rows])
    tv = vec[[i for i, r in enumerate(rows) if r['year'] == years[0]]]
    sv = vec[[i for i, r in enumerate(rows) if r['year'] == years[-1]]]
    model = Model(fit_rows(train, tv))
    pred = model.interest([r['title'] for r in test], [r['type'] for r in test], sv)
    p = np.array([model.in_slot(x['interest'], r['day'], {'morning': '08:00', 'midday': '12:00', 'afternoon': '15:30'}[r['block']])
                  for x, r in zip(pred, test)], dtype=float)
    a = np.array([r['peak'] for r in test], dtype=float)
    scale = np.median(a) / np.median(p)                 # a new year's overall level is unknown in advance
    err = np.abs(np.log(p * scale / a))
    rank = _spearman(p, a)
    rank_base = _spearman([model._base(r['type']) for r in test], a)
    big = 130
    hit = int(((p * scale >= big) & (a >= big)).sum())
    lines = [f'Fit on {years[0]} ({len(train)} sessions), predict {years[-1]} ({len(test)} sessions).',
             f'Typical error: x{math.exp(np.median(err)):.2f} (median); within x1.5 for {np.mean(err < math.log(1.5)):.0%} of sessions.',
             f'Rank correlation with actual peaks: {rank:.2f} (session type alone: {rank_base:.2f}).',
             f'Sessions that drew {big}+: {int((a >= big).sum())}; predicted {big}+: {int((p * scale >= big).sum())}; both: {hit}.',
             f'{years[-1]} overall level was x{scale:.2f} the model\'s (applied before computing the errors above).']
    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(data_dir, 'history', 'attendance_check.txt'), 'w', encoding='utf-8') as f:
        f.write(report + '\n')
    return report


def predict(data_dir, titles, types, day=None, start=None, embed=ollama_embed):
    import yaml
    model = load(data_dir)
    with open(os.path.join(data_dir, 'config.yaml'), encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    cutoffs, seats, sym_min = cfg.get('size_cutoffs'), cfg.get('room_sizes'), cfg.get('symposium_min_seats', 0)
    res = model.interest(titles, types, embed([session_text(t, y) for t, y in zip(titles, types)]))
    for x in res:
        if cutoffs:
            x['size'], x['size_note'] = model.size(x, x['type'], cutoffs, seats, sym_min)
        slot = f'  in {day} {start}: {model.in_slot(x["interest"], day, start)}' if day and start else ''
        size = f"  room: {x['size']}" + (f" ({x['size_note']})" if x['size_note'] else '') if cutoffs else ''
        print(f"{x['interest']:4d} ({x['low']}-{x['high']})  {x['type']:15s} {x['title']}{size}{slot}")
        for s in x['like']:
            print(f'       like {s}')
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('fit', 'check'):
        sub.add_parser(name).add_argument('data_dir')
    p = sub.add_parser('predict')
    p.add_argument('data_dir'); p.add_argument('--title'); p.add_argument('--type', default='contributed', choices=TYPES)
    p.add_argument('--sessions', help='a sessions.csv with title and kind columns'); p.add_argument('--day'); p.add_argument('--start')
    a = ap.parse_args()
    if a.cmd == 'fit':
        fit(a.data_dir)
    elif a.cmd == 'check':
        check(a.data_dir)
    else:
        if a.sessions:
            with open(a.sessions, encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            titles, types = [r['title'] for r in rows], [r['kind'] for r in rows]
        elif a.title:
            titles, types = [a.title], [a.type]
        else:
            sys.exit('give --title or --sessions')
        predict(a.data_dir, titles, types, a.day, a.start)


if __name__ == '__main__':
    main()
