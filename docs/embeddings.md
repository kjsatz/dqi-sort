# Embeddings

Embeddings place every talk as a vector so we can draw the topic map, find each talk's nearest neighbours, and flag weak fits. They are not used to decide sessions.

## Saved format

One file per model and input recipe: `DATA_DIR/embeddings/<model>__<recipe>.npz` (NumPy, compressed).

| Array | Shape | Contents |
| --- | --- | --- |
| `talk_id` | (N,) | Talk IDs, in the same order as the rows of `vector` |
| `vector` | (N, D) | Unit-length embeddings, float16 |
| `text_sha1` | (N,) | Hash of the exact text embedded |
| `meta` | () | JSON: model, backend, recipe, dimensions, prompt, date |

Load with `dqi_sort.embed.load(path)`, which returns `(talk_ids, vectors, meta)`. A file is about 7 MB for 5,000 talks at 768 dimensions. Re-running only embeds talks whose text changed, so late additions are cheap.

Recipes:

- `card`: title plus the summary card's platform, problem, approach, keywords and session topic.
- `abstract`: title plus abstract. SPECTER2 gets them as `title [SEP] abstract`, the format it was trained on.

## Running on a Mac

```
pip install -r requirements.txt

# Google EmbeddingGemma, through Ollama
ollama pull embeddinggemma
python -m dqi_sort.embed DATA_DIR --model embeddinggemma --recipe card
python -m dqi_sort.embed DATA_DIR --model embeddinggemma --recipe abstract

# AI2 SPECTER2, through Hugging Face (downloads about 0.5 GB the first time)
pip install torch transformers adapters
python -m dqi_sort.embed DATA_DIR --model specter2 --recipe card
python -m dqi_sort.embed DATA_DIR --model specter2 --recipe abstract
```

To add a model (for example a newer EmbeddingGemma), add a line to `MODELS` in `dqi_sort/embed.py`.

## Choosing a model

```
python -m dqi_sort.score_embeddings DATA_DIR DATA_DIR/reference/assignments_human_2026.csv
```

This scores every saved embedding against last year's human sessions: how often a talk's nearest neighbour is in the same session, and how well clusters match the sessions. Two files joined with `+` are scored as one combined embedding. Pick the best-scoring model and recipe for the year's run.
