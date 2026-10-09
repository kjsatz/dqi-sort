"""Can last year's human sort teach the embedding which directions matter? Hold out whole sessions."""
import json, numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA
from sklearn.preprocessing import normalize
W = '/home/claude/work/'
ids = json.load(open('ids.json')); t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
G = json.load(open(W + 'linked_groups.json')); idx = {i: k for k, i in enumerate(ids)}
y = np.array([t[i]['human_session'] for i in ids]); sess = sorted(set(y))
def nn1(X, sub):
    Xs = X[sub]; sim = Xs @ Xs.T; np.fill_diagonal(sim, -9)
    for a, i in enumerate(np.array(ids)[sub]):
        for j in G.get(i, []):
            b = np.where(np.array(ids)[sub] == j)[0]
            if len(b): sim[a, b] = -9
    return np.mean(y[sub][np.argmax(sim, 1)] == y[sub])
for name in ['E_mix.npy', 'E_raw.npy', 'E_facets.npy']:
    X = np.load(name); rng = np.random.default_rng(0); base = []; proj = []
    for rep in range(4):
        perm = rng.permutation(sess); folds = np.array_split(perm, 4)
        for f in folds:
            te = np.isin(y, f); tr = ~te
            lda = LDA(n_components=min(30, len(set(y[tr])) - 1), solver='eigen', shrinkage='auto').fit(X[tr], y[tr])
            Z = normalize(lda.transform(X))
            base.append(nn1(X, te)); proj.append(nn1(Z, te))
    print(f"{name:14s} held-out sessions nn1: raw embedding {np.mean(base):.3f}  ->  LDA-projected {np.mean(proj):.3f}")
