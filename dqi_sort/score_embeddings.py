"""Score saved embeddings against a reference sort (e.g. last year's human sessions).

    python -m dqi_sort.score_embeddings DATA_DIR REFERENCE.csv [EMBEDDING.npz ...]
    python -m dqi_sort.score_embeddings DATA_DIR REFERENCE.csv a.npz+b.npz    # concatenate two embeddings

With no embedding files given, scores every file in DATA_DIR/embeddings/.
REFERENCE.csv has the assignments.csv columns (talk_id, session_id, ...).

Metrics (multi-part partners are excluded as neighbours, since they are trivially similar):
    nn1_session    share of talks whose nearest other talk is in the same reference session
    top10_session  share of each talk's 10 nearest talks that are in its session
    ARI            agreement between a 1-cluster-per-session cut of the embedding and the reference
                   (0 = chance, 1 = identical)
"""
import csv, glob, os, sys
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score
from dqi_sort.embed import load

def load_combo(spec):
    parts = [load(p) for p in spec.split('+')]
    ids = parts[0][0]
    for p in parts[1:]: assert p[0] == ids, 'embedding files cover different talks'
    X = np.hstack([v - v.mean(0) for _, v, _ in parts])          # centre each, then join
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return ids, X

def main():
    data_dir, ref_path, specs = sys.argv[1], sys.argv[2], sys.argv[3:]
    specs = specs or sorted(glob.glob(os.path.join(data_dir, 'embeddings', '*.npz')))
    talks = {r['talk_id']: r for r in csv.DictReader(open(os.path.join(data_dir, 'talks.csv'), encoding='utf-8'))}
    ref = {r['talk_id']: r['session_id'] for r in csv.DictReader(open(ref_path)) if r['session_id']}
    print(f"{'embedding':55s} {'nn1_session':>11s} {'top10':>7s} {'ARI':>6s}")
    for spec in specs:
        ids, X = load_combo(spec)
        keep = [k for k, i in enumerate(ids) if i in ref and talks[i]['status'] == 'active']
        ids = [ids[k] for k in keep]; X = X[keep]
        y = np.array([ref[i] for i in ids]); ser = np.array([talks[i]['series'] or i for i in ids])
        sim = X @ X.T
        sim[ser[:, None] == ser[None, :]] = -9                       # self and multi-part partners
        order = np.argsort(-sim, axis=1)
        nn1 = np.mean(y[order[:, 0]] == y)
        top10 = np.mean(y[order[:, :10]] == y[:, None])
        lab = AgglomerativeClustering(n_clusters=len(set(y)), linkage='ward').fit_predict(X)
        name = ' + '.join(os.path.basename(s) for s in spec.split('+'))
        print(f"{name:55s} {nn1:11.3f} {top10:7.3f} {adjusted_rand_score(y, lab):6.3f}")

if __name__ == '__main__':
    main()
