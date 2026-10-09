# dqi-sort

Tools for sorting the APS Global Physics Summit DQI (Division of Quantum Information) abstracts into sessions, scheduling them into rooms, and recruiting chairs. The lead is Kevin Satzinger. Read `PROCESS.md` first: it is the agreed process, and the code should follow it.

## Hard rules

- **No abstracts, names or other conference data in this repo.** It is public. Every command takes the data folder (a separate private repo, e.g. `../dqi-2026-dryrun`) as an argument and never writes into this folder. `.gitignore` excludes data file types; keep it that way. Test fixtures must be made up.
- **Sorting never reads the reference sort.** Data repos may hold a past human sort under `reference/` (split out by the parser on intake). Only scoring and comparison read it; no sorting, proposal, packing or review step may.
- People decide at the checkpoints in `PROCESS.md`. Claude drafts, proposes and flags; it does not make the checkpoint decisions.
- Data in the private repo is plain CSV / JSONL, sorted by stable ID, so diffs are readable. Never delete talk rows; change their status.

## Layout

- `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline package. So far: `embed.py` (embeddings, saved as .npz), `score_embeddings.py` (score embeddings against a reference sort).
- `prompts/card_spec.md`: the Haiku presentation-card prompt (`{CATEGORIES}` and `{UNITS}` are filled from config).
- `config.example.yaml`: config template, including the list of other APS units.
- `docs/embeddings.md`: how to run and compare embedding models.
- `prototype/`: scripts and prompts from the first test on the 2026 superconducting sheet. Reference only; hard-coded paths.

## Status (Oct 9, 2026)

Done: the 2026 superconducting test (see `prototype/README.md`), the process design, the card spec, the embedding step (tested with a small local model only).

Next, for a dry run on the full 2026 DQI workbook before abstracts arrive on about Nov 9:

1. APS workbook parser into the data format, driven by the column map in `config.yaml`: repairs encoding damage (keeping the raw text), and splits any existing session assignments into `reference/`. Plus the reverse writer for the final APS sheet.
2. Card generation through the Haiku API (Batch API), including the malformed-text flag, then the linking step (multi-part series across categories; affiliation to institution).
3. Validators (the checks listed in `PROCESS.md`) as one command, and a pre-commit hook here that refuses data files.
4. Run EmbeddingGemma (via Ollama) and SPECTER2 on Kevin's Mac and score them (`docs/embeddings.md`).
5. Area proposals and packing (from the prototype prompts), with the packing report as a pull-request description.
6. Review sheets: `sync-sheets` (shared sheet updated in place, new area sheet per checked-in area, stamped with the commit) and intake with three-way comparison.
7. Scheduling solver, talk-order step, chair handoff.

Dry-run inputs are ready in `../dqi-2026-dryrun/input/` (see its `CLAUDE.md`), including the virtual track and the session-chair volunteer lists.

Still needed from Kevin, not blocking the dry run: an Anthropic API key for the Haiku cards; a Google service account for `sync-sheets`; this year's division number (24?); the real 2027 room grid and room distances; processed RFID attendance; the chair invitation template and the return format agreed with the coordinator; reviewers for each area.
