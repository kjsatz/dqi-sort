"""Validate a session proposal.  usage: python3 validate.py cards.json proposal.json [--all]
cards.json: {id: card_text}.  proposal.json: {"sessions":[{"title","scope","talks":[ids in order]}], "released":[{"id","reason","suggested_home"}]}
Rules: invited = 3 units, oral = 1; session must total 15 units (13-15 tolerated with warning);
at most 2 invited per session; every input id exactly once (in a session or released; --all: no releases);
LINKED multi-part talks must be in the same session, consecutive, in the listed order."""
import json, sys, re
cards = json.load(open(sys.argv[1])); P = json.load(open(sys.argv[2])); require_all = '--all' in sys.argv
inv = {i for i, c in cards.items() if 'INVITED' in c.split('|')[0]}
linked = {}
for i, c in cards.items():
    m = re.search(r'LINKED multi-part.*?: (.*)', c)
    if m: linked[i] = m.group(1).strip().split(' -> ')
errs, warns, seen = [], [], {}
for k, s in enumerate(P['sessions']):
    units = sum(3 if i in inv else 1 for i in s['talks'])
    ninv = sum(i in inv for i in s['talks'])
    tag = f"session {k} '{s.get('title','')[:40]}'"
    if units > 15 or units < 13: errs.append(f"{tag}: {units} units (need 15; 13-14 tolerated)")
    elif units < 15: warns.append(f"{tag}: {units} units (15 preferred)")
    if ninv > 2: errs.append(f"{tag}: {ninv} invited talks (max 2)")
    for pos, i in enumerate(s['talks']):
        if i not in cards: errs.append(f"{tag}: unknown id {i}")
        if i in seen: errs.append(f"id {i} appears twice")
        seen[i] = (k, pos)
for r in P.get('released', []):
    i = r['id']
    if i not in cards: errs.append(f"released unknown id {i}")
    if i in seen: errs.append(f"id {i} both placed and released / duplicated")
    seen[i] = ('released', 0)
missing = [i for i in cards if i not in seen]
if missing: errs.append(f"{len(missing)} ids missing: {missing[:20]}")
if require_all and P.get('released'): errs.append(f"{len(P['released'])} talks released but --all requires placing everything")
for i, grp in linked.items():
    grp = [g for g in grp if g in cards]
    locs = [seen.get(g) for g in grp]
    if any(l is None for l in locs): continue
    if any(l[0] == 'released' for l in locs):
        if not all(l[0] == 'released' for l in locs): errs.append(f"linked group {grp}: some released, some placed")
        continue
    if len({l[0] for l in locs}) > 1: errs.append(f"linked group {grp} split across sessions")
    elif [l[1] for l in locs] != list(range(locs[0][1], locs[0][1] + len(grp))): errs.append(f"linked group {grp} not consecutive/in order")
n_placed = sum(1 for v in seen.values() if v[0] != 'released')
print(f"sessions: {len(P['sessions'])}, placed: {n_placed}, released: {len(P.get('released', []))}, input: {len(cards)}")
for w in warns: print("WARN", w)
for e in errs: print("ERROR", e)
print("OK" if not errs else f"{len(errs)} errors")
