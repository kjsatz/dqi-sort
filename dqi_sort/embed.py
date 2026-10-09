"""Embed talks and save the vectors.

    python -m dqi_sort.embed DATA_DIR --model embeddinggemma --recipe card
    python -m dqi_sort.embed DATA_DIR --model specter2 --recipe abstract

Writes DATA_DIR/embeddings/<model>__<recipe>.npz containing:
    talk_id    (N,)   str      talk IDs, same order as vector rows
    vector     (N, D) float16  L2-normalised embeddings
    text_sha1  (N,)   str      hash of the exact text embedded, for incremental updates
    meta       ()     str      JSON: model, backend, recipe, dims, prompt, created

Re-running only embeds talks whose text changed (or that are new), so late changes are cheap.
Withdrawn talks are kept; filter on talks.csv status when using the vectors.

Models (add more in MODELS):
    embeddinggemma  Google EmbeddingGemma via Ollama (`ollama pull embeddinggemma`), task prompt for clustering
    embeddinggemma-st  the same model via sentence-transformers (Hugging Face; accept the Gemma terms first)
    specter2        AI2 SPECTER2 (allenai/specter2_base + proximity adapter), trained on scientific papers
    nomic           nomic-embed-text via Ollama
    bge-small-onnx  a small local ONNX model, for testing without downloads (set DQI_ONNX_DIR)
"""
import argparse, datetime, hashlib, json, os, sys
import numpy as np

CLUSTER_PROMPT = 'task: clustering | query: '

MODELS = {
    'embeddinggemma':    {'backend': 'ollama', 'name': 'embeddinggemma', 'prompt': CLUSTER_PROMPT},
    'embeddinggemma-st': {'backend': 'sentence-transformers', 'name': 'google/embeddinggemma-300m', 'prompt': CLUSTER_PROMPT},
    'specter2':          {'backend': 'specter2', 'name': 'allenai/specter2_base', 'adapter': 'allenai/specter2', 'prompt': ''},
    'nomic':             {'backend': 'ollama', 'name': 'nomic-embed-text', 'prompt': 'clustering: '},
    'bge-small-onnx':    {'backend': 'onnx', 'name': 'bge-small-en-v1.5', 'prompt': ''},
}


# ---------- input texts ----------
def load_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return {r['talk_id']: r for r in map(json.loads, f)}

def texts_for(data_dir, recipe, model):
    abstracts = load_jsonl(os.path.join(data_dir, 'abstracts.jsonl'))
    cards = load_jsonl(os.path.join(data_dir, 'cards.jsonl')) if recipe == 'card' else {}
    out = {}
    for tid, a in sorted(abstracts.items()):
        if recipe == 'abstract':
            if MODELS[model]['backend'] == 'specter2':
                out[tid] = (a['title'], a['body'] or '')          # SPECTER2 wants title [SEP] abstract
            else:
                out[tid] = f"{a['title']}. {a['body'] or ''}"
        elif recipe == 'card':
            c = cards[tid]
            out[tid] = (f"{a['title']}. Platform: {c['platform']}. Problem: {c['problem']}. "
                        f"Approach: {c['approach']}. Keywords: {', '.join(c['keywords'])}. "
                        f"Session topic: {c['session_pitch']}.")
        else:
            sys.exit(f'unknown recipe {recipe!r} (use card or abstract)')
    return out

def sha1(x):
    s = x if isinstance(x, str) else ' [SEP] '.join(x)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


# ---------- backends: each takes a list of texts and returns an (n, D) float array ----------
def run_ollama(cfg, texts, host=os.environ.get('OLLAMA_HOST', 'http://localhost:11434')):
    import urllib.request
    out = []
    for k in range(0, len(texts), 64):
        body = json.dumps({'model': cfg['name'], 'input': [cfg['prompt'] + t for t in texts[k:k + 64]]}).encode()
        req = urllib.request.Request(host.rstrip('/') + '/api/embed', body, {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as r:
            out.extend(json.load(r)['embeddings'])
    return np.array(out, dtype=np.float32)

def run_sentence_transformers(cfg, texts):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(cfg['name'])
    return m.encode(texts, prompt=cfg['prompt'] or None, batch_size=32, show_progress_bar=True)

def run_specter2(cfg, pairs):
    import torch
    from transformers import AutoTokenizer
    from adapters import AutoAdapterModel
    tok = AutoTokenizer.from_pretrained(cfg['name'])
    model = AutoAdapterModel.from_pretrained(cfg['name'])
    model.load_adapter(cfg['adapter'], source='hf', load_as='specter2', set_active=True)
    model.eval()
    out = []
    for k in range(0, len(pairs), 16):
        batch = [p if isinstance(p, str) else p[0] + tok.sep_token + p[1] for p in pairs[k:k + 16]]
        enc = tok(batch, padding=True, truncation=True, max_length=512, return_tensors='pt', return_token_type_ids=False)
        with torch.no_grad():
            out.append(model(**enc).last_hidden_state[:, 0, :].numpy())
    return np.vstack(out)

def run_onnx(cfg, texts):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    d = os.environ['DQI_ONNX_DIR']
    tok = Tokenizer.from_file(os.path.join(d, 'tokenizer.json')); tok.enable_truncation(512); tok.enable_padding()
    sess = ort.InferenceSession(os.path.join(d, 'onnx', 'model.onnx'), providers=['CPUExecutionProvider'])
    names = [i.name for i in sess.get_inputs()]; out = []
    for k in range(0, len(texts), 32):
        enc = tok.encode_batch(texts[k:k + 32])
        feed = {'input_ids': np.array([e.ids for e in enc], dtype=np.int64),
                'attention_mask': np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if 'token_type_ids' in names: feed['token_type_ids'] = np.zeros_like(feed['input_ids'])
        out.append(sess.run(None, feed)[0][:, 0])
    return np.vstack(out)

BACKENDS = {'ollama': run_ollama, 'sentence-transformers': run_sentence_transformers,
            'specter2': run_specter2, 'onnx': run_onnx}


# ---------- save / load ----------
def path_for(data_dir, model, recipe):
    return os.path.join(data_dir, 'embeddings', f'{model}__{recipe}.npz')

def load(path):
    """Return (talk_ids, vectors float32, meta dict)."""
    z = np.load(path, allow_pickle=False)
    return list(z['talk_id']), z['vector'].astype(np.float32), json.loads(str(z['meta']))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data_dir'); ap.add_argument('--model', required=True, choices=MODELS)
    ap.add_argument('--recipe', default='card', choices=['card', 'abstract'])
    ap.add_argument('--full', action='store_true', help='re-embed everything, ignoring the saved file')
    a = ap.parse_args()
    cfg = MODELS[a.model]
    texts = texts_for(a.data_dir, a.recipe, a.model)
    ids = list(texts); hashes = [sha1(texts[i]) for i in ids]
    out_path = path_for(a.data_dir, a.model, a.recipe)
    old = {}
    if os.path.exists(out_path) and not a.full:
        z = np.load(out_path, allow_pickle=False)
        old = {t: (h, v) for t, h, v in zip(z['talk_id'], z['text_sha1'], z['vector'])}
    todo = [k for k, (i, h) in enumerate(zip(ids, hashes)) if old.get(i, (None,))[0] != h]
    print(f'{len(ids)} talks; {len(ids) - len(todo)} unchanged, embedding {len(todo)} with {a.model}')
    new = BACKENDS[cfg['backend']](cfg, [texts[ids[k]] for k in todo]) if todo else np.zeros((0, 1))
    dims = new.shape[1] if len(todo) else len(next(iter(old.values()))[1])
    vec = np.zeros((len(ids), dims), dtype=np.float32); fresh = dict(zip(todo, new))
    for k, i in enumerate(ids):
        v = fresh[k] if k in fresh else old[i][1].astype(np.float32)
        vec[k] = v / np.linalg.norm(v)
    meta = {'model': a.model, 'backend': cfg['backend'], 'name': cfg['name'], 'recipe': a.recipe, 'dims': dims,
            'prompt': cfg['prompt'], 'created': datetime.datetime.now().isoformat(timespec='seconds')}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.savez_compressed(out_path, talk_id=np.array(ids), vector=vec.astype(np.float16),
                        text_sha1=np.array(hashes), meta=np.array(json.dumps(meta)))
    print(f'wrote {out_path}: {len(ids)} x {dims}, {os.path.getsize(out_path) / 1e6:.1f} MB')

if __name__ == '__main__':
    main()
