"""Drop axis fields; resolve multi-part groups; write compact talk cards."""
import json, glob, re, collections, csv
t = {x['id']: x for x in json.load(open('talks.json'))}
S = {}
for f in sorted(glob.glob('summaries/*.json')):
    for s in json.load(open(f)):
        s.pop('primary_axis', None); s.pop('secondary_axis', None)
        S[s['id']] = s
ids = list(t)

# multi-part groups (same logic as partners2.py) -> connected components
def stem(title): return re.split(r'\(?\bpart\b', title.lower())[0].strip(' -–:,(')
def toks(s): return set(re.findall(r'[a-z0-9]+', s.lower()))
mp = [i for i in ids if S[i].get('multi_part')]
adj = collections.defaultdict(set)
for i in mp:
    hint = S[i]['multi_part'].get('partner_hint') or ''
    for j in mp:
        if j == i: continue
        st = stem(t[j]['title'])
        if (stem(t[i]['title']) == st and len(st) > 15) or \
           (len(toks(st) & toks(hint)) / max(1, len(toks(st))) > 0.8 and len(st) > 15) or \
           t[j]['name'].lower() in hint.lower():
            adj[i].add(j); adj[j].add(i)
group, seen = {}, set()
for i in mp:
    if i in seen: continue
    comp, stack = [], [i]
    while stack:
        k = stack.pop()
        if k in seen: continue
        seen.add(k); comp.append(k); stack += list(adj[k])
    comp.sort(key=lambda k: (S[k]['multi_part'].get('part') or 0))
    for k in comp: group[k] = comp
json.dump({k: v for k, v in group.items()}, open('linked_groups.json', 'w'), indent=0)
print('linked groups:', len({tuple(v) for v in group.values()}), 'talks in groups:', len(group))

def card(i):
    s, x = S[i], t[i]
    typ = 'INVITED(36min,3 units)' if x['type'] != 'Oral' else 'oral'
    parts = [f"[{i}] {typ} | {x['title']} | speaker: {x['name']}",
             f"  platform: {s['platform']}; problem: {s['problem']}; approach: {s['approach']}",
             f"  claim: {s['key_claim']}",
             f"  keywords: {', '.join(s['keywords'])}"]
    if i in group:
        others = [k for k in group[i] if k != i]
        parts.append(f"  LINKED multi-part (keep consecutive, same session): {' -> '.join(group[i])}")
    if s.get('constraints'): parts.append(f"  constraints: {s['constraints']}")
    if s.get('other_unit'): parts.append(f"  maybe-other-unit: {s['other_unit']}")
    return "\n".join(parts)
cards = {i: card(i) for i in ids}
json.dump(cards, open('cards.json', 'w'), indent=0, ensure_ascii=False)
json.dump(S, open('summaries_clean.json', 'w'), indent=1, ensure_ascii=False)
txt = "\n".join(cards.values())
print('cards chars:', len(txt), '~tokens', len(txt)//4)
print(cards[ids[0]]); print(cards[mp[0]])

# drop axis columns from the delivered CSV
rows = list(csv.DictReader(open('out/haiku_summaries_2026_superconducting.csv', encoding='utf-8')))
cols = [c for c in rows[0] if c not in ('primary_axis', 'secondary_axis')]
with open('out/haiku_summaries_2026_superconducting.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, cols, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
print('csv cols:', len(cols))
