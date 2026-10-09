"""usage: python3 validate_plan.py cards.json plan.json"""
import json, sys, re, collections
cards = json.load(open(sys.argv[1])); P = json.load(open(sys.argv[2]))
inv = {i for i, c in cards.items() if 'INVITED' in c.split('|')[0]}
S = P['sessions']; errs = []
if len(S) != 43: errs.append(f"{len(S)} sessions; need exactly 43")
codes = [s['code'] for s in S]
if len(set(codes)) != len(codes): errs.append("duplicate session codes")
seen = collections.Counter(i for s in S for i in s.get('invited', []))
for i in inv:
    if seen[i] != 1: errs.append(f"invited {i} assigned {seen[i]} times (need exactly 1)")
for i in seen:
    if i not in inv: errs.append(f"{i} listed as invited but is not an invited talk")
cap = 0
for s in S:
    n = len(s.get('invited', []))
    if n > 2: errs.append(f"{s['code']}: {n} invited (max 2)")
    for k in ('code', 'title', 'scope', 'family'):
        if not s.get(k): errs.append(f"{s.get('code')}: missing {k}")
    cap += 15 - 3 * n
est = sum(s.get('est_orals', 0) for s in S)
n_oral = len(cards) - len(inv)
print(f"sessions {len(S)}, oral capacity {cap}, orals to place {n_oral}, sum est_orals {est}, families {len(set(s.get('family') for s in S))}")
if cap < n_oral: errs.append("oral capacity below number of orals")
for e in errs: print("ERROR", e)
print("OK" if not errs else f"{len(errs)} errors")
