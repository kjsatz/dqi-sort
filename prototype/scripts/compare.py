"""Compare a Claude proposal with the human sort.  usage: python3 compare.py DIR"""
import json, sys, collections, itertools
W = '/home/claude/work/'
t = {x['id']: x for x in json.load(open(W + 'talks.json'))}
meta = json.load(open(W + 'meta.json'))['sessions']
def pairs(groups):
    return {frozenset(p) for g in groups for p in itertools.combinations(g, 2)}
def compare(P, show=True):
    C = [s['talks'] for s in P['sessions']]
    placed = [i for g in C for i in g]
    hum = collections.defaultdict(list)
    for i in placed: hum[t[i]['human_session']].append(i)
    cp, hp = pairs(C), pairs(hum.values())
    prec = len(cp & hp) / len(cp) if cp else 0
    rec = len(cp & hp) / len(hp) if hp else 0
    out = {'sessions': len(C), 'placed': len(placed), 'released': len(P.get('released', [])),
           'pair_precision': round(prec, 3), 'pair_recall': round(rec, 3)}
    if show:
        for s in P['sessions']:
            cnt = collections.Counter(t[i]['human_session'] for i in s['talks'])
            print(f"\n## {s['title']}\n   human sessions: " + ", ".join(f"{k}:{v}" for k, v in cnt.most_common()))
        rel = collections.Counter(t[r['id']]['human_session'] for r in P.get('released', []))
        print("\nreleased talks came from human sessions:", dict(rel.most_common()))
    return out
if __name__ == '__main__':
    d = sys.argv[1]
    P = json.load(open(f'{d}/proposal.json'))
    o = compare(P)
    # where did each human session that is mostly inside this bucket go?
    cards = json.load(open(f'{d}/cards.json'))
    inb = collections.Counter(t[i]['human_session'] for i in cards)
    where = {i: k for k, s in enumerate(P['sessions']) for i in s['talks']}
    print("\nhuman session -> Claude session index (R = released), for human sessions with >=8 talks in bucket:")
    for h, n in inb.most_common():
        if n < 8: continue
        members = [i for i in t if t[i]['human_session'] == h]
        dest = collections.Counter(where.get(i, 'R' if i in cards else 'out') for i in members)
        print(f"  {h:10s} {meta[h]['title'][:45]:45s} {dict(dest.most_common())}")
    print(json.dumps(o))
