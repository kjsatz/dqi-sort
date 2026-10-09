import json, itertools, collections, sys
from sklearn.metrics import adjusted_rand_score
W = '/home/claude/work/'
t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
def lab_from(P): return {i: s.get('code', str(k)) for k, s in enumerate(P['sessions']) for i in s['talks']}
def lab_human(): return {i: t[i]['human_session'] for i in t}
def pairs(lab):
    g = collections.defaultdict(list)
    for i, s in lab.items(): g[s].append(i)
    return {frozenset(p) for m in g.values() for p in itertools.combinations(m, 2)}
def cmp(a, b):
    ids = sorted(set(a) & set(b)); pa, pb = pairs({i: a[i] for i in ids}), pairs({i: b[i] for i in ids})
    inter = len(pa & pb)
    return dict(shared_pairs_frac_of_a=round(inter / len(pa), 3), shared_pairs_frac_of_b=round(inter / len(pb), 3),
                ARI=round(adjusted_rand_score([a[i] for i in ids], [b[i] for i in ids]), 3))
if __name__ == '__main__':
    L = {'human': lab_human()}
    for f in sys.argv[1:]: L[f] = lab_from(json.load(open(f)))
    names = list(L)
    for x, y in itertools.combinations(names, 2): print(f"{x:22s} vs {y:22s}", cmp(L[x], L[y]))
