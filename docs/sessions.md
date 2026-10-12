# Session drafts and the global pass

Stages 5 and 6 of `PROCESS.md` (Drafting and the global pass). Claude agents run as subagents inside Claude Code (Opus), not through the API. Code: `dqi_sort/sessions.py` (drafts) and `dqi_sort/pack.py` (global pass); prompts in `prompts/session_spec.md`, `prompts/pack_spec.md` and `prompts/critique_spec.md`.

## Stage 5: drafts

1. `python -m dqi_sort.sessions prepare DATA_DIR` writes, per work area, `DATA_DIR/work/sessions/AREA/`: `cards.txt` (a compact card per talk; bridge talks marked "near OTHER" when at least 7 of their 10 nearest neighbours are in other areas), `brief.md`, `prompt.md` and `talks.json`.
2. In Claude Code, launch one Opus subagent per area, in parallel: "Read `DATA_DIR/work/sessions/AREA/prompt.md` and do exactly what it says. Read only the files it names. Write only proposal.json in that folder." Each runs `python -m dqi_sort.sessions check` until it prints OK.

A draft session holds 8 to 12 units (an oral talk is 1, an invited talk 3); its length is not chosen yet. Talks with no good home in the area are released to the pool, bridge talks first. Virtual sessions are final at this stage (120 minutes; speakers share a time window).

## Stage 6: the global pass

1. `python -m dqi_sort.pack start DATA_DIR` collects the drafts into `work/pack/state.json` and writes the working files: `overview.md` (every session and its talks; the pool with full cards), `check.md` (the length check), `candidates.md` (short lists from the embeddings) and `prompt.md`.
2. Launch one Opus subagent: "Read `DATA_DIR/work/pack/prompt.md` and do exactly what it says." It applies moves in batches with `python -m dqi_sort.pack ops DATA_DIR OPS.json`, each with a reason, until `pack status` says FITS.
3. Critique round (before people see it): `python -m dqi_sort.pack critique DATA_DIR` writes one folder per review area; launch one Opus critic per folder ("Read `.../critique/AREA/prompt.md` and do exactly what it says"). Then launch the global agent again with the same prompt: it weighs the suggestions and keeps the sort fitting. Repeat if a round still changes a lot.
4. `python -m dqi_sort.pack finish DATA_DIR --replace` writes `sorting/sessions.csv`, `sorting/assignments.csv`, `sorting/moves.csv`, `views/sessions.md`, `views/sessions/AREA.md` (with coherence, weakest fits, attendance estimates and suggested room sizes; Ollama must be running) and `views/packing_report.md`.
5. Commit the data repo on a branch and open a pull request with `views/packing_report.md` as its description. The lead reviews and merges; then `python -m dqi_sort.sheets sync DATA_DIR` makes the review sheets.

The length check: a 144-minute session holds 12 units (11 allowed), a 108-minute one 9 (8 allowed). Given the slots of each length, it picks the lengths that need the fewest talk moves and lists each session that must grow or shrink. Session IDs are the draft area and a number (`QEC07`), or `X01`, `X02`... for sessions built in the global pass; review areas are assigned at the end (the area most of a session's talks were drafted in).
