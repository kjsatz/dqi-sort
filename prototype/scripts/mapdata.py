import json, numpy as np, umap, collections
from sklearn.cluster import AgglomerativeClustering
W = '/home/claude/work/'
ids = json.load(open('ids.json')); t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
meta = json.load(open(W + 'meta.json'))['sessions']
S = json.load(open(W + 'summaries_clean.json'))
X = np.load('E_mix.npy')
FAM = json.load(open(W + 'prototype_constants.json'))['map_families']   # family -> human session codes
fam = {s: f for f, v in FAM.items() for s in v.split()}
F = json.load(open('/home/claude/sessbuild/run_a/final.json'))
plan = {s['code']: s for s in json.load(open('/home/claude/sessbuild/run_a/plan.json'))['sessions']}
cl = {i: s['code'] for s in F['sessions'] for i in s['talks']}
ctitle = {s['code']: s['title'] for s in F['sessions']}
xy = umap.UMAP(n_neighbors=15, min_dist=0.15, metric='cosine', random_state=42).fit_transform(X)
xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0))
sim = X @ X.T; np.fill_diagonal(sim, -9); nb = np.argsort(-sim, 1)[:, :10]
emb_cl = AgglomerativeClustering(n_clusters=43, linkage='ward').fit_predict(X)
pts = []
for k, i in enumerate(ids):
    x = t[i]
    pts.append({'id': i, 'x': round(float(xy[k, 0]), 4), 'y': round(float(xy[k, 1]), 4), 'title': x['title'], 'speaker': x['name'],
                'inv': x['type'] != 'Oral', 'hs': x['human_session'], 'cs': cl[i], 'cat': x['category'], 'ec': int(emb_cl[k]),
                'kw': ', '.join(S[i]['keywords'][:4]),
                'nb': [[int(j), round(float(sim[k, j]), 3)] for j in nb[k]]})
out = {'points': pts, 'human_sessions': {s: {'title': v['title'], 'family': fam[s]} for s, v in meta.items()},
       'claude_sessions': {c: {'title': ctitle[c], 'family': plan[c]['family']} for c in ctitle},
       'categories': json.load(open(W + 'meta.json'))['categories'], 'human_families': list(FAM)}
json.dump(out, open('mapdata.json', 'w'), separators=(',', ':'), ensure_ascii=False)
# how often a talk's 10 nearest neighbours share its session, per sort
for lab, key in [('human', 'hs'), ('claude', 'cs'), ('embedding clusters', 'ec')]:
    v = np.array([p[key] for p in pts]); print(lab, round(float(np.mean(v[nb] == v[:, None])), 3))
import os; print(os.path.getsize('mapdata.json') // 1024, 'KB')
