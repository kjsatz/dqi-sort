# Presentation cards

Stage 2 of `PROCESS.md`. Claude Haiku writes one card per talk from its title, abstract, submitter notes and affiliation, following `prompts/card_spec.md`. The cards run as Haiku subagents inside Claude Code, not through the API. Code: `dqi_sort/cards.py`.

## Steps

1. `python -m dqi_sort.cards prepare DATA_DIR` (batches of 50) writes `DATA_DIR/work/cards/prompt.md` (the spec with this year's categories and other units filled in) and `batch_NNN.json` files for every active talk without a card. Speaker names are never included. Talks with no abstract are skipped and listed.
2. In Claude Code, launch one Haiku subagent per batch (they run in parallel). Each reads `prompt.md` and its batch, writes `batch_NNN.out.json`, and runs `python -m dqi_sort.cards check` on it until it prints OK.
3. `python -m dqi_sort.cards merge DATA_DIR` checks every output against its batch and adds the valid cards to `cards.jsonl`. A batch with problems is listed and skipped; rerun it alone.
4. Delete the merged outputs in `work/cards/` (`prepare` refuses to run while unmerged outputs are there). `work/` is not committed.

To redo particular talks (a fixed abstract, a late addition), list their IDs in a file and run `prepare --ids FILE`.

## Full run (Oct 2026, 2026 dry run)

All 1,929 talks in 20 batches of about 100, one Haiku subagent each, all in parallel: about 15 minutes of wall time and about 4 million Haiku tokens. Every batch passed the checker. Flags: 18 leadership review, 155 other unit (11 "belongs there"), 65 malformed, 164 parts of multi-part talks. Several agents hit their output limit writing 100 cards in one go and had to write in pieces, so the default batch is now 50 (about 40 agents).

Since then the `malformed` flag was narrowed to text too damaged to tell what the talk is about (typos and small damage are not our problem), and the repair step was dropped.

## Pilot (Oct 2026, 50 talks)

Every card passed the checker on the first or second try, about three minutes per batch of 25. On 23 talks that also have cards from the earlier API test, the best category agreed for 20. Constraints, multi-part series and other-unit suggestions were picked up well. Two kinds of false "malformed" flags (HTML formatting, and series that share one abstract) led to a clarification in the spec.
