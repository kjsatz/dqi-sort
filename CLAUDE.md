# dqi-sort

Tools for sorting the APS Global Physics Summit DQI (Division of Quantum Information) abstracts into sessions, scheduling them into rooms, and recruiting chairs. The lead in 2027 was Kevin Satzinger; each year has its own lead. Read `RUNBOOK.md` first (the steps in order, with the commands), then `PROCESS.md` (the agreed process; the code should follow it). In any session, `python -m dqi_sort.status DATA_DIR` says where the run stands and what is next.

## Hard rules

- **No abstracts, names or other conference data in this repo.** It is public. Every command takes the data folder (a separate private repo, e.g. `../dqi-2026-dryrun`) as an argument and never writes into this folder. `.gitignore` excludes data file types; keep it that way. Test fixtures must be made up.
- **Sorting never reads the reference sort.** Data repos may hold a past human sort under `reference/` (split out by the parser on intake). Only scoring and comparison read it; no sorting, proposal, packing or review step may.
- **The in-person and virtual tracks are a hard partition.** No step may move a talk between them; the drafts, the global pass and their checks refuse it.
- People decide at the checkpoints in `PROCESS.md`. Claude drafts, proposes and flags; it does not make the checkpoint decisions.
- Data in the private repo is plain CSV / JSONL, sorted by stable ID, so diffs are readable. Never delete talk rows; change their status.
- `main` is protected by two rulesets: never push to it. Work on a branch and open a pull request; the `checks` workflow (no data files, tests) must pass, and a pull request needs one approving review. The repo admin (Kevin in 2027) may bypass the review for their own pull requests (the ones Claude opens): merge with `gh pr merge N --squash --admin` once `checks` passes, and only when they ask. Collaborators cannot approve or merge their own. Enable the local hook once per clone with `git config core.hooksPath .githooks`.

## Layout

- `RUNBOOK.md`: the steps of a run in order, with commands, checkpoints, 2027's dates and lessons. `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline package. So far: `intake.py` (stage 1: APS export to `talks.csv` and `abstracts.jsonl`; re-runnable, keeps later-stage columns; applies the lead's expected invited topics and overrides, and drops APS boilerplate notes), `textfix.py` (minimal text repair: encoding damage and hidden HTML comments only; other HTML is left as submitted), `embed.py` (EmbeddingGemma via Ollama on each talk's card, saved as `embeddings/cards.npz`), `cards.py` (stage 2: batch files for Haiku subagents, check, merge; `docs/cards.md`), `attendance.py` (attendance model fitted on past RFID peaks; `docs/attendance.md`), `attendance_report.py` (refits and writes the model report with figures into the data repo's `history/`), `linking.py` (stage 3: series candidates, pair requests and affiliation list for one Claude agent, `prompts/linking_spec.md`; apply the decisions to `talks.csv`), `areas.py` (stage 4: review areas from `config.yaml` by card category plus an embedding-neighbour check; writes `views/areas.md` and `views/flags.md`, the one list of talks the lead must decide, led by the talks held for the lead in `sorting/held.csv`), `sessions.py` (stage 5: per-area draft files for one Opus agent each, and the draft check), `pack.py` (stage 6, the global pass: state, moves with reasons, length check, embedding candidate lists, critique round, finish writes `sorting/` and the packing report; `docs/sessions.md`).
- `scripts/check_no_data.py`: refuses data files (run by `.githooks/pre-commit` and by `.github/workflows/checks.yml`).
- `tests/`: pytest, with made-up fixtures in `tests/fixtures/`. Set up with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; run `.venv/bin/python -m pytest tests`.
- `prompts/card_spec.md`: the Haiku presentation-card prompt (`{CATEGORIES}` and `{UNITS}` are filled from config).
- `prompts/session_spec.md`, `pack_spec.md`, `critique_spec.md`: the prompts for the stage 5 drafts, the global pass and its critics.
- `config.example.yaml`: config template, including the list of other APS units.
- `docs/`: how to run the embeddings, cards and attendance model, and how to set up Google Sheets access (`google_sheets.md`).
- `dqi_sort/gsheets.py`: Google sign-in (OAuth as the lead) and Drive folder setup. `dqi_sort/sheets.py`: `sync` writes the shared sheet and new area sheets from the sort in git (`review.py` reads them back).
- `chairs.py` (stage 10: volunteers linked to their abstracts; one recruiting spreadsheet with a tab per review area from round 1, kept in step with git; confirmed chairs placed on sessions without clashes once scheduled). `order.py` (stage 9: invited-talk positions per room, sessions re-ordered around their invited talk, the check). `schedule.py` (stage 8: room sizes against the grid, then the solver that puts sessions into room-time slots). `review.py` (stage 7: read a returned area sheet, apply the reviewer's changes three-way, move talks while acting on notes). `decide.py`: the lead's decisions on a talk's status (offer to another unit, exchanged, returned, received, poster, keep, duplicate, withdraw), logged with date and unit in `sorting/status_log.csv`. `validate.py`: every check in `PROCESS.md` as one command, with the reconciliation of APS's abstract list against the delivered one (`--delivery` for the strict checks). `deliver.py` (the reconciliation, and a copy of APS's 2026-style page; superseded by `aps_fill.py` for APS's own sheet). `late.py` (late add, withdraw and move, each committed and checked). `aps_fill.py` (stage 11 in APS's 2027 layout: writes our in-person sessions, chairs and each talk's Session and Order into APS's own sheet, one In-Person Sorting tab, never the Virtual tab; `check` reads it back and compares it with the sort in git).
- `schedule_page.py` with the template `schedule_page.html`: the schedule as one self-contained page (rooms by time blocks, sessions and room headings coloured on one attendance scale, a line per room on what it holds, talks per session); `--dry-run` runs `schedule budget` and `solve` on a copy of HEAD first.
- `overview.py` with the template `overview_page.html`: the whole sort on one self-contained page from one commit of the data repo (a column per review area, a bar of talk squares per session coloured by embedding fit, an attendance dial, popups with abstracts; `docs/overview.md`).
- `workbook.py`, `mockgrid.py`, `score.py`: past-year dry runs (read old sorting workbooks, make a 2027-format grid, score against the human sort with a blind judge; `docs/dry_runs.md`).
- `aps_input.py`: APS's sheets in, read-only (`check` the format against the config, `pull` a dated snapshot and the intake inputs, `diff` two snapshots, `volunteers` for chairs). `status.py`: each stage done or not and the next command. `new_year.py`: next year's data folder from this year's.

## Status (Nov 18, 2026)

The 2027 run is done: APS's sorting sheet holds the 201 in-person sessions with chairs and talk order (read back to
match), the 6 virtual sessions were submitted Nov 10, and APS entered our schedule into its grid (checked Nov 18). The
record is in `../dqi-2027` (`checkpoints.md`, `open_questions.md`, `aps_email.md`).

Settled choices (keep it simple; pick one good approach rather than comparing options):

- Embeddings: EmbeddingGemma via Ollama, on the card only. No other models or recipes. Used for routing, bridge talks, the global pass's candidate lists, session coherence, review areas, suggested chairs and similar sessions.
- Agent steps run as subagents in Claude Code on the lead's subscription, not the Anthropic API: Haiku for cards, Opus for linking, drafts, the global pass, critics and talk order.

Dry runs on the 2023-2026 abstracts (Oct 2026): each year's sort fits its grid, and a blind Claude judge rates Claude's sessions about 1 point higher than the human sorts on its 1-to-5 coherence scale. Summary: `../dqi-2027/reports/dry_runs_2023-2026.md` (private); method in `docs/dry_runs.md`.

Next year: a new lead starts with `RUNBOOK.md` (Set up: `new_year`, the config TODOs, `aps_input check`). After the 2027 meeting, add its RFID data to the attendance history and refit (RUNBOOK.md, After the meeting).
