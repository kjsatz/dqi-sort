"""Capacity-constrained assignment from the talk x session fit matrix (CP-SAT).
usage: python3 solve.py RUNDIR"""
import json, sys, glob, collections
from ortools.sat.python import cp_model
d = sys.argv[1].rstrip('/') + '/'
W = '/home/claude/work/'
t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
G = json.load(open(W + 'linked_groups.json'))
plan = json.load(open(d + 'plan.json'))['sessions']
codes = [s['code'] for s in plan]
inv_of = {s['code']: s['invited'] for s in plan}
fit = collections.defaultdict(dict)
for f in glob.glob(d + 'assign/batch_*.out.json'):
    for r in json.load(open(f)):
        for c in r['choices']:
            fit[r['id']][c['code']] = max(fit[r['id']].get(c['code'], 0), c['fit'])
orals = [i for i in t if t[i]['type'] == 'Oral']
assert set(orals) == set(fit), (len(orals), len(fit))
VAL = {3: 10, 2: 6, 1: 2}
OFF = -30          # any session not chosen by the assigner: allowed only as a last resort
# extra links and avoid-pairs from submitter notes: [[talk, talk], ...] and [[talk, invited talk, why], ...]
ML = json.load(open(W + 'prototype_constants.json'))['manual_links']
together = [g for g in {tuple(v) for v in G.values()}] + [tuple(p) for p in ML['together']]
m = cp_model.CpModel()
x = {(i, c): m.NewBoolVar(f"x{i}_{c}") for i in orals for c in codes}
for i in orals: m.AddExactlyOne(x[i, c] for c in codes)
for g in together:
    for a, b in zip(g, g[1:]):
        for c in codes: m.Add(x[a, c] == x[b, c])
avoid = {(i, c) for i, inv, *_ in ML['avoid'] for c in codes if inv in inv_of[c]}
for (i, c) in avoid: m.Add(x[i, c] == 0)
for c in codes:
    units = 3 * len(inv_of[c]) + sum(x[i, c] for i in orals)
    m.Add(units <= 15); m.Add(units >= 13)
m.Maximize(sum((VAL[fit[i][c]] if c in fit[i] else OFF) * x[i, c] for i in orals for c in codes))
sol = cp_model.CpSolver(); sol.parameters.max_time_in_seconds = 120; sol.parameters.num_workers = 8
st = sol.Solve(m); print(sol.StatusName(st), sol.ObjectiveValue())
assign = {i: next(c for c in codes if sol.Value(x[i, c])) for i in orals}
got = collections.Counter(fit[i].get(assign[i], 0) for i in orals)
top = sum(assign[i] == max(fit[i], key=fit[i].get) for i in orals)
print("placed at fit 3/2/1/unchosen:", got[3], got[2], got[1], got[0], "| got assigner's first-ranked:", top, "/", len(orals))
out = {"sessions": []}
for s in plan:
    members = s['invited'] + [i for i in orals if assign[i] == s['code']]
    out["sessions"].append({"code": s['code'], "title": s['title'], "talks": members})
json.dump(out, open(d + 'solved.json', 'w'), indent=1)
json.dump({i: fit[i] for i in orals}, open(d + 'fit_matrix.json', 'w'), indent=0)
