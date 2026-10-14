# dqi-sort

Tools for sorting the APS Global Physics Summit DQI (Division of Quantum Information) abstracts into sessions, scheduling them into rooms, and recruiting chairs. The lead is Kevin Satzinger. Read `PROCESS.md` first: it is the agreed process, and the code should follow it.

## Hard rules

- **No abstracts, names or other conference data in this repo.** It is public. Every command takes the data folder (a separate private repo, e.g. `../dqi-2026-dryrun`) as an argument and never writes into this folder. `.gitignore` excludes data file types; keep it that way. Test fixtures must be made up.
- **Sorting never reads the reference sort.** Data repos may hold a past human sort under `reference/` (split out by the parser on intake). Only scoring and comparison read it; no sorting, proposal, packing or review step may.
- **The in-person and virtual tracks are a hard partition.** No step may move a talk between them; the drafts, the global pass and their checks refuse it.
- People decide at the checkpoints in `PROCESS.md`. Claude drafts, proposes and flags; it does not make the checkpoint decisions.
- Data in the private repo is plain CSV / JSONL, sorted by stable ID, so diffs are readable. Never delete talk rows; change their status.
- `main` is protected: never push to it. Work on a branch and open a pull request; the `checks` workflow (no data files, tests) must pass. Enable the local hook once per clone with `git config core.hooksPath .githooks`.

## Layout

- `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline package. So far: `intake.py` (stage 1: APS export to `talks.csv` and `abstracts.jsonl`; re-runnable, keeps later-stage columns), `textfix.py` (minimal text repair: encoding damage and hidden HTML comments only; other HTML is left as submitted), `embed.py` (EmbeddingGemma via Ollama on each talk's card, saved as `embeddings/cards.npz`), `cards.py` (stage 2: batch files for Haiku subagents, check, merge; `docs/cards.md`), `attendance.py` (attendance model fitted on past RFID peaks; `docs/attendance.md`), `attendance_report.py` (refits and writes the model report with figures into the data repo's `history/`), `linking.py` (stage 3: series candidates, pair requests and affiliation list for one Claude agent, `prompts/linking_spec.md`; apply the decisions to `talks.csv`), `areas.py` (stage 4: review areas from `config.yaml` by card category plus an embedding-neighbour check; writes `views/areas.md` and `views/flags.md`, the one list of talks the lead must decide, led by the talks held for the lead in `sorting/held.csv`), `sessions.py` (stage 5: per-area draft files for one Opus agent each, and the draft check), `pack.py` (stage 6, the global pass: state, moves with reasons, length check, embedding candidate lists, critique round, finish writes `sorting/` and the packing report; `docs/sessions.md`).
- `scripts/check_no_data.py`: refuses data files (run by `.githooks/pre-commit` and by `.github/workflows/checks.yml`).
- `tests/`: pytest, with made-up fixtures in `tests/fixtures/`. Set up with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; run `.venv/bin/python -m pytest tests`.
- `prompts/card_spec.md`: the Haiku presentation-card prompt (`{CATEGORIES}` and `{UNITS}` are filled from config).
- `prompts/session_spec.md`, `pack_spec.md`, `critique_spec.md`: the prompts for the stage 5 drafts, the global pass and its critics.
- `config.example.yaml`: config template, including the list of other APS units.
- `docs/`: how to run the embeddings, cards and attendance model, and how to set up Google Sheets access (`google_sheets.md`).
- `dqi_sort/gsheets.py`: Google sign-in (OAuth as the lead) and Drive folder setup. `dqi_sort/sheets.py`: `sync` (sync-sheets) writes the shared sheet and new area sheets from the sort in git; reading returned sheets back is still to do.
- `chairs.py` (stage 10: volunteers linked to their abstracts; one recruiting spreadsheet with a tab per review area from round 1, kept in step with git; confirmed chairs placed on sessions without clashes once scheduled). `order.py` (stage 9: invited-talk positions per room, sessions re-ordered around their invited talk, the check). `schedule.py` (stage 8: room sizes against the grid, then the solver that puts sessions into room-time slots). `review.py` (stage 7: read a returned area sheet, apply the reviewer's changes three-way, move talks while acting on notes). `decide.py`: the lead's decisions on a talk's status (offer to another unit, exchanged, returned, received, poster, keep, duplicate, withdraw), logged with date and unit in `sorting/status_log.csv`. `validate.py`: every check in `PROCESS.md` as one command, with the reconciliation of APS's abstract list against the delivered one (`--delivery` for the strict checks). `deliver.py` (stage 11: the sort written into a copy of APS's sorting page, one long page per track, plus the reconciliation). `late.py` (late add, withdraw and move, each committed and checked).
- `workbook.py`, `mockgrid.py`, `score.py`: past-year dry runs (read old sorting workbooks, make a 2027-format grid, score against the human sort with a blind judge; `docs/dry_runs.md`).
- `prototype/`: scripts and prompts from the first test on the 2026 superconducting sheet. Reference only; hard-coded paths.

## Status (Oct 13, 2026)

Done: the 2026 superconducting test (see `prototype/README.md`), the process design, the card spec, the APS parser, the attendance model (fitted on 2025 and 2026; data, model and report in `history/` of the private `../dqi-2027` repo), review sheets (`sync-sheets`, writing only). On the dry run: stages 1-4 including the lead's checkpoint (cards and embeddings for all talks; 82 series; 10 areas + virtual), and a first stage 5 run with the old design (one agent per area with a fixed share of the grid; 201 sessions, 39 lonely talks). That run showed fixed shares leave no room to combine lonely talks, so stages 4-6 were redesigned (`PROCESS.md`, Drafting and the global pass).

Settled choices (keep it simple; pick one good approach rather than comparing options):

- Embeddings: EmbeddingGemma via Ollama, on the card only. No other models or recipes. Used for routing, bridge talks, the global pass's candidate lists, session coherence and review areas.
- Haiku cards: run as Haiku subagents in Claude Code on Kevin's subscription, not the Anthropic API. Session drafts and the global pass: Opus subagents, likewise.

Second dry-run sort (Oct 12) with the new design, then (Oct 13) dry runs on 2023, 2024 and 2025 and a 2026 rerun: each year's sort fits its grid, and a blind Claude judge rates Claude's sessions about 1 point higher (1-5) than the human sorts, with a third as many out-of-place talks (2025, 2026; 2023 in `views/scores.md` of its repo). Improvements tested there and adopted: swap partners for the critics, review areas by content, the drafts' length mix, keep-apart requests, near-duplicate sessions across areas, the duplicate-invited flag. Summary: `../dqi-2027/reports/dry_runs_2023-2026.md` (private).

Dry run 2 (Oct 13) rehearsed stages 1-11 on the 2026 abstracts with every checkpoint; the lead's decisions are in `checkpoints.md` of `../dqi-2026-dryrun`. Built on the way: the lead's decisions on talks (`decide.py`), the review read-back (`review.py`), room sizes and the scheduling solver with the session grid sheet (`schedule.py`), talk order (`order.py`), chair recruiting in one spreadsheet with a tab per area (`chairs.py`), the validator, the APS delivery sheet and the late-change tools.

Next, when the 2027 inputs arrive (abstracts about Nov 9): the 2027 config from APS's inputs (division code, categories, column map, rooms and grid, symposia, volunteer lists) and intake; then, first thing, before the cards, reconcile the invited speakers in APS's sheet against the lead's list of expected invited speakers and topics (`PROCESS.md`, When the abstracts arrive).

Dry-run inputs are ready in `../dqi-2026-dryrun/input/` (see its `CLAUDE.md`), including the virtual track and the session-chair volunteer lists.

Still needed from Kevin: the list of expected invited speakers and topics (he has it; invited talks arrive with no abstract); this year's division number (24?); the real 2027 room grid and room distances; reviewers (who also recruit chairs) for each area.
