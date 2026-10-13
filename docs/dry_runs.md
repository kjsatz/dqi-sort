# Dry runs on past years

A dry run sorts a past year's DQI abstracts from scratch with the current process, then scores the result against the
human sort of that year. Use it to test a change to the process before abstracts arrive. Each year lives in its own
private data repo (`dqi-2023-dryrun` to `dqi-2026-dryrun`); together with `dqi-2027/history/` (attendance) they are
the archive of past years.

## Setting up a year

1. Download the year's sorting workbook(s) from Google Sheets as .xlsx (File → Download → Microsoft Excel) into
   `DATA_DIR/input/raw/`. Ideally both the workbook as it was when sorting started and the final sorted one(s).
2. Extract the inputs (the 2026 APS export layout) and the human sort with `python -m dqi_sort.workbook` (`extract`
   for the in-person and virtual tables, `reference` for the sorted tabs). Each year's workbook is laid out
   differently: find the tabs by looking at them (the commands used are in each repo's `input/README.md`). Invited
   talks listed with no abstract get a placeholder naming their submission category.
3. Copy `config.yaml` from another dry-run year and set `aps_input`. Keep the 2026 categories and areas: cards pick a
   category by content, so a year's own numbering does not matter. Set `reference_sort: reference/final_talks.csv`.
4. `python -m dqi_sort.intake DATA_DIR`, then `python -m dqi_sort.mockgrid DATA_DIR` for a made-up 2027-format grid
   (put the printed `session_budget` in config.yaml).
5. Run the stages as for a real year: cards (`docs/cards.md`), embeddings (`docs/embeddings.md`), linking, areas,
   drafts and the global pass (`docs/sessions.md`). Checkpoints are skipped: keep every talk and list the flags.

## Scoring

- `python -m dqi_sort.score metrics DATA_DIR` compares the sort with the human one on the card embeddings
  (coherence, own-session-nearest) and on how many same-session pairs agree. These move little; use them to catch
  regressions.
- The blind judge is the real test: `python -m dqi_sort.score judge-prepare DATA_DIR` samples sessions from both
  sorts under neutral labels; one Opus agent rates them (`work/judge/prompt.md`); `judge-report` unblinds the ratings.
  Human sessions in past years were longer (180 minutes), which makes them harder to keep coherent; compare out-of-place
  talks per 10 talks as well as the 1-5 rating.

Results go to `views/scores.md` in the data repo.
