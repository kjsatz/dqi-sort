import json, collections
D = json.load(open('mapdata.json')); W = '/home/claude/work/'
S = json.load(open(W + 'summaries_clean.json'))
HF = json.load(open(W + 'prototype_constants.json'))['map_human_families']   # family -> human session codes
hf = {s: f for f, v in HF.items() for s in v.split()}
for s, v in D['human_sessions'].items(): v['family'] = hf[s]
# label embedding clusters by their most frequent keywords
mem = collections.defaultdict(list)
for p in D['points']: mem[p['ec']].append(p['id'])
ecl = {}
for c, m in mem.items():
    cnt = collections.Counter(k for i in m for k in S[i]['keywords'][:4])
    ecl[str(c)] = {'title': ' · '.join(k for k, _ in cnt.most_common(3)), 'family': ''}
D['emb_clusters'] = ecl
for p in D['points']:
    p['ec'] = str(p['ec']); p['nb'] = [[a, round(b, 2)] for a, b in p['nb']]
D['human_families'] = list(HF)
D['claude_families'] = list(dict.fromkeys(v['family'] for v in D['claude_sessions'].values()))
del D['categories']
json.dump(D, open('mapdata2.json', 'w'), separators=(',', ':'), ensure_ascii=False)
print(D['claude_families'], len(open('mapdata2.json').read()) // 1024, 'KB')
