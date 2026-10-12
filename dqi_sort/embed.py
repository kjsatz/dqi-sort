"""Embed every talk's presentation card with Google EmbeddingGemma (via Ollama) and save the vectors.

    ollama pull embeddinggemma
    python -m dqi_sort.embed DATA_DIR

Embeds the card, not the abstract or title, so every talk is described in the same uniform terms
rather than in its authors' own style. Writes DATA_DIR/embeddings/cards.npz containing:
    talk_id    (N,)   str      talk IDs, same order as vector rows
    vector     (N, D) float16  L2-normalised embeddings
    text_sha1  (N,)   str      hash of the exact text embedded, for incremental updates
    meta       ()     str      JSON: model, prompt, dims, created

Re-running only embeds talks whose card changed (or that are new), so late changes are cheap.
Withdrawn talks are kept; filter on talks.csv status when using the vectors.
"""
import argparse, datetime, hashlib, json, os, urllib.request
import numpy as np

MODEL = 'embeddinggemma'
PROMPT = 'task: clustering | query: '          # EmbeddingGemma's task prompt for clustering
OLLAMA = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')


def load_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return {r['talk_id']: r for r in map(json.loads, filter(str.strip, f))}


def card_text(c):
    return (f"Platform: {c['platform']}. Problem: {c['problem']}. Approach: {c['approach']}. "
            f"Finding: {c['key_claim']} Keywords: {', '.join(c['keywords'])}. Session topic: {c['session_pitch']}.")


def sha1(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def run_ollama(texts):
    out = []
    for k in range(0, len(texts), 64):
        body = json.dumps({'model': MODEL, 'input': [PROMPT + t for t in texts[k:k + 64]]}).encode()
        req = urllib.request.Request(OLLAMA.rstrip('/') + '/api/embed', body, {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as r:
            out.extend(json.load(r)['embeddings'])
    return np.array(out, dtype=np.float32)


def path_for(data_dir):
    return os.path.join(data_dir, 'embeddings', 'cards.npz')


def load(path):
    """Return (talk_ids, vectors float32, meta dict)."""
    z = np.load(path, allow_pickle=False)
    return list(z['talk_id']), z['vector'].astype(np.float32), json.loads(str(z['meta']))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir')
    ap.add_argument('--full', action='store_true', help='re-embed everything, ignoring the saved file')
    a = ap.parse_args()
    cards = load_jsonl(os.path.join(a.data_dir, 'cards.jsonl'))
    ids = sorted(cards, key=lambda i: (len(i), i))
    texts = [card_text(cards[i]) for i in ids]
    hashes = [sha1(t) for t in texts]
    out_path = path_for(a.data_dir)
    old = {}
    if os.path.exists(out_path) and not a.full:
        z = np.load(out_path, allow_pickle=False)
        old = {t: (h, v) for t, h, v in zip(z['talk_id'], z['text_sha1'], z['vector'])}
    todo = [k for k, (i, h) in enumerate(zip(ids, hashes)) if old.get(i, (None,))[0] != h]
    print(f'{len(ids)} cards; {len(ids) - len(todo)} unchanged, embedding {len(todo)} with {MODEL}')
    new = run_ollama([texts[k] for k in todo]) if todo else np.zeros((0, 1))
    dims = new.shape[1] if len(todo) else len(next(iter(old.values()))[1])
    vec = np.zeros((len(ids), dims), dtype=np.float32)
    fresh = dict(zip(todo, new))
    for k, i in enumerate(ids):
        v = fresh[k] if k in fresh else old[i][1].astype(np.float32)
        vec[k] = v / np.linalg.norm(v)
    meta = {'model': MODEL, 'prompt': PROMPT, 'dims': dims,
            'created': datetime.datetime.now().isoformat(timespec='seconds')}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.savez_compressed(out_path, talk_id=np.array(ids), vector=vec.astype(np.float16),
                        text_sha1=np.array(hashes), meta=np.array(json.dumps(meta)))
    print(f'wrote {out_path}: {len(ids)} x {dims}, {os.path.getsize(out_path) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
