# dqi-sort

Tools for sorting the APS Global Physics Summit DQI (Division of Quantum Information) abstracts into sessions, scheduling them into rooms, and recruiting chairs. The lead is Kevin Satzinger. Read `PROCESS.md` first: it is the agreed process, and the code should follow it.

## Hard rules

- **No abstracts, names or other conference data in this repo.** It is public. Every command takes the data folder (a separate private repo, e.g. `../dqi-2026-dryrun`) as an argument and never writes into this folder. `.gitignore` excludes data file types; keep it that way. Test fixtures must be made up.
- **Sorting never reads the reference sort.** Data repos may hold a past human sort under `reference/` (split out by the parser on intake). Only scoring and comparison read it; no sorting, proposal, packing or review step may.
- People decide at the checkpoints in `PROCESS.md`. Claude drafts, proposes and flags; it does not make the checkpoint decisions.
- Data in the private repo is plain CSV / JSONL, sorted by stable ID, so diffs are readable. Never delete talk rows; change their status.
- `main` is protected: never push to it. Work on a branch and open a pull request; the `checks` workflow (no data files, tests) must pass. Enable the local hook once per clone with `git config core.hooksPath .githooks`.
- `review/process-base` and `review/process` exist only for the PROCESS.md review pull request (the base lacks PROCESS.md so every line can take a comment). Never merge it. Agreed changes to PROCESS.md go to `main` in their own pull request.

## Layout

- `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline package. So far: `intake.py` (stage 1: APS export to `talks.csv` and `abstracts.jsonl`; re-runnable, keeps later-stage columns), `textfix.py` (minimal text repair: encoding damage and hidden HTML comments only; other HTML is left as submitted), `embed.py` (EmbeddingGemma via Ollama on each talk's card, saved as `embeddings/cards.npz`).
- `scripts/check_no_data.py`: refuses data files (run by `.githooks/pre-commit` and by `.github/workflows/checks.yml`).
- `tests/`: pytest, with made-up fixtures in `tests/fixtures/`. Set up with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; run `.venv/bin/python -m pytest tests`.
- `prompts/card_spec.md`: the Haiku presentation-card prompt (`{CATEGORIES}` and `{UNITS}` are filled from config).
- `config.example.yaml`: config template, including the list of other APS units.
- `docs/embeddings.md`: how to run the embeddings.
- `prototype/`: scripts and prompts from the first test on the 2026 superconducting sheet. Reference only; hard-coded paths.

## Status (Oct 12, 2026)

Done: the 2026 superconducting test (see `prototype/README.md`), the process design, the card spec, the APS parser (`python -m dqi_sort.intake DATA_DIR`, run on the dry run), the embedding step (EmbeddingGemma on cards; not yet run).

Settled choices (keep it simple; pick one good approach rather than comparing options):

- Embeddings: EmbeddingGemma via Ollama, on the card only. No other models or recipes.
- Haiku cards: run as Haiku subagents in Claude Code on Kevin's subscription, not the Anthropic API.

Next, for a dry run on the full 2026 DQI workbook before abstracts arrive on about Nov 9. Do 0-6 and scoring first; they answer whether the sort is good.

- Stage 0: made-up venue in the 2027 format (`venue/rooms.csv`, `schedule/slots.csv`; see the dry-run repo's `CLAUDE.md`).
- Stage 2, cards: batch files for Haiku subagents, then validate and merge into `cards.jsonl` (pilot about 50 talks first). Then embed.
- Stage 3, linking: multi-part series across categories; affiliation to institution.
- Stages 4-6: areas and flags, session proposals, packing (OR-Tools; packing chooses 144 or 108 minutes per session within the slots available), with the packing report as a pull request in the data repo.
- Scoring: blind judge of Claude's sort against the 2026 human sort; check flagged talks against those that left DQI.
- Validators (the checks listed in `PROCESS.md`) as one command.
- Stages 8-9: attendance estimate (embeddings of past sessions plus slot features; censored for rooms at capacity), scheduling solver, talk order.
- Stages 7, 10, 11: review sheets (`sync-sheets`), chair handoff, reverse writer for the final APS sheet.

Dry-run inputs are ready in `../dqi-2026-dryrun/input/` (see its `CLAUDE.md`), including the virtual track and the session-chair volunteer lists.

Still needed from Kevin: RFID attendance for 2025 and 2026 (per session: entries, peak inside, average visit; we model the peak, with peak at 90% or more of capacity treated as full) and whether 2025 abstracts and sessions exist or only titles; a Google service account for `sync-sheets` (not needed until review sheets); this year's division number (24?); the real 2027 room grid and room distances; the chair invitation template and the return format agreed with the coordinator; reviewers for each area.
