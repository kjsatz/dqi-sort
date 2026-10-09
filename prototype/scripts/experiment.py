import json, numpy as np, sys
sys.path.insert(0, '/home/claude/work'); sys.path.insert(0, '/home/claude/emb')
from embedder import embed
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score
W = '/home/claude/work/'
t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
S = json.load(open(W + 'summaries_clean.json'))
G = json.load(open(W + 'linked_groups.json'))
exec(open(W + 'rep2.py').read().split('fam={')[0].split('FAM=')[1].join(['FAM=', '']) if False else '')
FAM = json.load(open(W + 'prototype_constants.json'))['families']   # family -> human session codes
fam = {s: f for f, v in FAM.items() for s in v.split()}
ids = list(t); n = len(ids); idx = {i: k for k, i in enumerate(ids)}
y = np.array([t[i]['human_session'] for i in ids]); yf = np.array([fam[v] for v in y])
cl = {i: s['code'] for s in json.load(open('/home/claude/sessbuild/run_a/final.json'))['sessions'] for i in s['talks']}
yc = np.array([cl[i] for i in ids])
mask = np.zeros((n, n), bool)            # exclude multi-part partners (trivially similar)
for i, g in G.items():
    for j in g: mask[idx[i], idx[j]] = True
np.fill_diagonal(mask, True)
kw = lambda i: ', '.join(S[i]['keywords'])
texts = {
 'raw title+abstract': lambda i: t[i]['title'] + '. ' + t[i]['body'],
 'title only': lambda i: t[i]['title'],
 'summary sentence (key claim)': lambda i: S[i]['key_claim'],
 'topic card': lambda i: f"Platform: {S[i]['platform']}. Problem: {S[i]['problem']}. Approach: {S[i]['approach']}. Keywords: {kw(i)}. Fits a session on: {S[i]['session_pitch']}.",
 'title + topic card': lambda i: f"{t[i]['title']}. Platform: {S[i]['platform']}. Problem: {S[i]['problem']}. Keywords: {kw(i)}. Session: {S[i]['session_pitch']}.",
}
def metrics(X, sparse=False):
    sim = (X @ X.T); sim = sim.toarray() if sparse else sim
    sim = sim.copy(); sim[mask] = -9; o = np.argsort(-sim, 1)
    Xd = X.toarray() if sparse else X
    lab = AgglomerativeClustering(n_clusters=43, linkage='ward').fit_predict(Xd)
    return {'nn1_session': np.mean(y[o[:, 0]] == y), 'top10_session': np.mean(y[o[:, :10]] == y[:, None]),
            'nn1_family': np.mean(yf[o[:, 0]] == yf), 'ARI_43_vs_human': adjusted_rand_score(y, lab),
            'nn1_claude_session': np.mean(yc[o[:, 0]] == yc), 'ARI_43_vs_claude': adjusted_rand_score(yc, lab)}
R = {}; E = {}
for name, f in texts.items():
    T = [f(i) for i in ids]
    R['tfidf | ' + name] = metrics(normalize(TfidfVectorizer(sublinear_tf=True, stop_words='english', ngram_range=(1, 2)).fit_transform(T)), True)
    E[name] = embed(T)
    R['bge | ' + name] = metrics(E[name])
    Xc = E[name] - E[name].mean(0); R['bge centered | ' + name] = metrics(normalize(Xc))
# facet embeddings: platform, problem, keywords embedded separately, concatenated
F = {k: embed([g(i) for i in ids]) for k, g in [('platform', lambda i: S[i]['platform']), ('problem', lambda i: S[i]['problem']),
                                                ('kw', lambda i: kw(i)), ('pitch', lambda i: S[i]['session_pitch'])]}
for wts in [(1, 1, 1, 1), (2, 1, 1, 1), (1, 1, 1, 2)]:
    Xf = np.hstack([w * (F[k] - F[k].mean(0)) for w, k in zip(wts, ['platform', 'problem', 'kw', 'pitch'])])
    R[f'bge facets plat/prob/kw/pitch w={wts}'] = metrics(normalize(Xf))
Xmix = normalize(np.hstack([normalize(E['raw title+abstract'] - E['raw title+abstract'].mean(0)), normalize(E['title + topic card'] - E['title + topic card'].mean(0))]))
R['bge centered raw ⊕ title+card'] = metrics(Xmix)
np.save('E_titlecard.npy', E['title + topic card']); np.save('E_raw.npy', E['raw title+abstract']); np.save('E_mix.npy', Xmix)
np.save('E_facets.npy', normalize(np.hstack([F[k] - F[k].mean(0) for k in ['platform', 'problem', 'kw', 'pitch']])))
json.dump(ids, open('ids.json', 'w'))
print(f"{'representation':52s} nn1_ses top10 nn1_fam ARI_h  nn1_cl ARI_cl")
for k, v in R.items(): print(f"{k:52s} " + "  ".join(f"{x:.3f}" for x in v.values()))
json.dump({k: {a: round(float(b), 3) for a, b in v.items()} for k, v in R.items()}, open('results.json', 'w'), indent=1)
