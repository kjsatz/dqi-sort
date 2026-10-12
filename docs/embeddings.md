# Embeddings

Embeddings place every talk as a vector so we can draw the topic map, find each talk's nearest neighbours, flag weak fits, and estimate attendance from similar past sessions. They are not used to decide sessions.

We use one model and one input: Google EmbeddingGemma, run locally through Ollama, on each talk's presentation card (platform, problem, approach, key finding, keywords and session topic). Embedding the card rather than the abstract or title gives every talk a uniform description, free of its authors' writing style. Nothing leaves the machine.

## Running on a Mac

```
brew install ollama
ollama pull embeddinggemma
python -m dqi_sort.embed DATA_DIR
```

Re-running only embeds talks whose card changed, so late additions are cheap. `--full` re-embeds everything.

## Saved format

`DATA_DIR/embeddings/cards.npz` (NumPy, compressed):

| Array | Shape | Contents |
| --- | --- | --- |
| `talk_id` | (N,) | Talk IDs, in the same order as the rows of `vector` |
| `vector` | (N, D) | Unit-length embeddings, float16 |
| `text_sha1` | (N,) | Hash of the exact text embedded |
| `meta` | () | JSON: model, prompt, dimensions, date |

Load with `dqi_sort.embed.load(path)`, which returns `(talk_ids, vectors, meta)`. A file is about 7 MB for 5,000 talks at 768 dimensions.
