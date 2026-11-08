# Overview page

One page with the whole sort, zoomed out: each review area is a column and each session an entry. Code:
`dqi_sort/overview.py`, with the page template `dqi_sort/overview_page.html`.

```
python -m dqi_sort.overview DATA_DIR                 # from HEAD
python -m dqi_sort.overview DATA_DIR --commit a1b2c3d   # from any earlier commit
```

It reads the data exactly as it is in that commit (uncommitted changes are ignored) and writes
`DATA_DIR/views/overview.html`, stamped with the commit. The page is one self-contained file: no network, no
libraries. It holds abstracts, so it lives in the private data repo, like every other view. Commit it with the
change it shows. The attendance dials need Ollama running; `--no-attendance` leaves them out.

## What it shows

- **Session entry:** an attendance dial, the session ID and title, and a bar with one square per contributed talk,
  a triple-width box per invited talk, and an outlined square for each 12 minutes still free.
- **Talk colour: fit.** This is the cosine similarity between the talk's card embedding and the centroid of the
  rest of its session, the per-talk value behind the packing report's coherence (`docs/sessions.md`). About 0.85 is
  unrelated and 0.95 very close. Colours follow matplotlib's Spectral map from 0.73 (red, poor fit) through pale
  yellow to 0.99 (blue, good fit), the full range of sort v1 (0.731 to 0.986); values outside take the end colour.
  Change `FIT_RANGE` in `overview.py` to rescale.
- **Dial: expected attendance.** This is the session's rank by the attendance model among all in-person sessions,
  from 0 (lowest) to 1 (highest). Ties share their rank. Virtual sessions have no estimate (`docs/attendance.md`).
- **Popups.** Hover over a talk, or focus it with the keyboard, to see:
  - its speaker, institution and category
  - its fit, and the closest other session in the same track with that session's similarity
  - its card summary and full abstract

  Hover over a session's title to see:
  - its length and how much is filled
  - its coherence (the mean fit)
  - its scope
  - the estimated peak attendance and range

  Click to pin a popup so you can scroll the abstract. Click again, press Esc or click elsewhere to close it.

## Viewing it

GitHub shows an HTML file in a repository as source code, not as a page. To view it, pull the data repo and open
`views/overview.html` in a browser. GitHub Pages could serve it, but a Pages site built from a private repo is
public on personal plans, so do not use Pages for this page.
