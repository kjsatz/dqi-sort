# Presentation cards

Stage 2 of `PROCESS.md`. Claude Haiku writes one card per talk from its title, abstract, submitter notes and affiliation, following `prompts/card_spec.md`. The cards run as Haiku subagents inside Claude Code, not through the API. Code: `dqi_sort/cards.py`.

## Steps

1. `python -m dqi_sort.cards prepare DATA_DIR` (batches of 50) writes `DATA_DIR/work/cards/prompt.md` (the spec with this year's categories and other units filled in) and `batch_NNN.json` files for every active talk without a card. Speaker names are never included. Talks with no abstract are skipped and listed.
2. In Claude Code, launch one Haiku subagent per batch (`model: haiku`), giving each the text of `work/cards/agent_task.md` (written by `prepare`) with `NNN` replaced by its batch number. Each reads `prompt.md` and its batch, writes `batch_NNN.out.json`, and runs `python -m dqi_sort.cards check` on it until it prints OK.
   - **At most 20 at once.** Claude Code runs at most 20 subagents at a time (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`); a launch beyond that is refused. Start the first 20, then start the next batch each time one finishes.
   - **Part files are named by batch.** An agent that writes its output in pieces must name them `batch_NNN.part1.json` etc. in `work/cards/`, never a generic name in a shared scratch folder: parallel agents share the scratchpad, and in Nov 2026 one agent joined another's part file.
   - **The check catches a card written for another talk**: besides the talk IDs, order and affiliations, it fails any card that shares almost no content words with its own talk's title and abstract.
3. `python -m dqi_sort.cards merge DATA_DIR` checks every output against its batch and adds the valid cards to `cards.jsonl`. A batch with problems is listed and skipped; rerun it alone.
4. Delete the merged outputs in `work/cards/` (`prepare` refuses to run while unmerged outputs are there). `work/` is not committed.

To redo particular talks (a fixed abstract, a late addition), list their IDs in a file and run `prepare --ids FILE`.

## Real run (Nov 2026, 2027 abstracts)

All 1,929 talks in 39 batches of 50, Haiku subagents in two waves (the 20-agent limit), about 2-4 minutes per batch and about 25 minutes of wall time in all. Every batch passed the checker; a cross-check of every card against its own talk (IDs, affiliations, shared content words) found no mismatches, after one agent had to rebuild half its output because another agent's part file had the same generic name. Those lessons are now in `agent_task.md` and the checker. Flags: 3 leadership review, 38 promotional, 53 other unit, 3 malformed (placeholder abstracts), 138 parts of multi-part talks. Embedding the cards took 17 s.

## Full run (Oct 2026, 2026 dry run)

All 1,929 talks in 20 batches of about 100, one Haiku subagent each, all in parallel: about 15 minutes of wall time and about 4 million Haiku tokens. Every batch passed the checker. Flags: 18 leadership review, 155 other unit (11 "belongs there"), 65 malformed, 164 parts of multi-part talks. Several agents hit their output limit writing 100 cards in one go and had to write in pieces, so the default batch is now 50 (about 40 agents).

Since then the `malformed` flag was narrowed to text too damaged to tell what the talk is about (typos and small damage are not our problem), and the repair step was dropped.

## Pilot (Oct 2026, 50 talks)

Every card passed the checker on the first or second try, about three minutes per batch of 25. On 23 talks that also have cards from the earlier API test, the best category agreed for 20. Constraints, multi-part series and other-unit suggestions were picked up well. Two kinds of false "malformed" flags (HTML formatting, and series that share one abstract) led to a clarification in the spec.
