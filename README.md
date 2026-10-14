# dqi-sort

Tools for sorting the Division of Quantum Information (DQI) abstracts for the APS Global Physics Summit into sessions, scheduling the sessions into rooms, recruiting session chairs, and handing the result back to APS. Claude drafts each step; people decide at fixed checkpoints.

The full process, data format and rules are in **[PROCESS.md](PROCESS.md)**. This page is the short version.

## The process

About 1,900 abstracts become about 200 sessions. In 2027, in-person sessions are 144 or 108 minutes long, built from 36-minute blocks: one invited talk, or three 12-minute contributed talks. The small virtual track is sorted on its own.

| Stage | What happens | Who decides |
| --- | --- | --- |
| 1. Intake | Read the APS export; repair text-encoding damage | |
| 2. Cards | Claude Haiku writes a standard card for each talk (topic, platform, claim, requests) | Spot-check |
| 3. Linking | Multi-part series and "put me with talk X" requests; affiliations normalized | Confirm unsure links |
| 4. Areas and flags | Talks split into 5–10 review areas; the few talks proposed for another unit or a poster are listed | **Lead decides** |
| 5. Drafts | One Claude agent per area groups its talks into sessions | |
| 6. Global pass | One agent with all of DQI in view fits the sessions to the slots; critics review each area | **Lead merges** |
| 7. Sort review | A Google Sheet per area; reviewers edit; Claude reads the edits back and finds homes for talks sent away | **Reviewers edit; lead merges** |
| 8. Schedule | Room sizes from an attendance model; a solver places sessions in room-time slots | **Lead approves** |
| 9. Talk order | Invited talks staggered across rooms; each session ordered around its invited talk | Spot-check |
| 10. Chairs | A recruiting spreadsheet, a tab per area, from review time; confirmed chairs placed without clashes | Area experts recruit |
| 11. Deliver | APS's sorting sheet filled in, validated, and reconciled with APS's abstract list; late adds, withdrawals and moves | **Lead approves each change** |

Principles:

- **People decide at checkpoints.** Claude drafts, proposes and flags. Each decision is logged in the lead's own words.
- **One DQI-wide sort.** Talks are grouped by content, not by submission category; review areas divide the work but talks move freely between them. Talks stay in DQI unless they have no quantum-information content.
- **Everything in git.** The sort is plain CSV in a private data repo; every move is a commit with a reason. The Google Sheets are views of it.
- **Two tracks, kept apart.** No step moves a talk between in person and virtual.

In dry runs on the 2023–2026 abstracts, each year's sort fit its grid, and a blind Claude judge rated Claude's sessions about one point higher (on 1–5) than the human sorts, with fewer out-of-place talks. Sessions are smaller in the 2027 format, which helps; expert review still decides. A full rehearsal of all eleven stages on the 2026 abstracts is done.

## Running it

Every command takes the private data folder as its argument (`DATA_DIR`, one repo per year, with a `config.yaml`; see [config.example.yaml](config.example.yaml)). Claude Code runs most of this; the agent steps write files that the commands check.

| Stage | Commands (`python -m dqi_sort.…`) |
| --- | --- |
| 1 | `intake DATA_DIR` |
| 2 | `cards prepare / merge`, `embed` ([docs/cards.md](docs/cards.md), [docs/embeddings.md](docs/embeddings.md)) |
| 3 | `linking prepare / apply` |
| 4 | `areas propose / flags / endgame`; the lead's decisions with `decide offer / exchanged / poster / keep / duplicate …` |
| 5–6 | `sessions prepare / check`, `pack start / ops / status / critique / finish` ([docs/sessions.md](docs/sessions.md)) |
| 7 | `sheets sync`, `review read / apply / move / homes` ([docs/google_sheets.md](docs/google_sheets.md)) |
| 8 | `schedule budget / solve / check / swap / grid` |
| 9 | `order positions / prepare / apply / check` |
| 10 | `chairs sync` |
| 11 | `validate [--delivery]`, `deliver`, `late add / withdraw / move` |
| Scoring | `score metrics / judge-prepare / judge-report` ([docs/dry_runs.md](docs/dry_runs.md)) |

Each module's docstring (`python -m dqi_sort.<module> -h`) explains its options.

## Feedback on the process

Open an [issue](https://github.com/kjsatz/dqi-sort/issues), or comment on any line of [PROCESS.md](PROCESS.md) in a pull request. Questions, objections and "this won't work because..." are all welcome.

## Contributing

- **No conference data in this repo.** It is public. Abstracts, names, emails, sorts, schedules and anything made from them live in the private data repos. Test data must be made up.
- `main` is protected: branch and open a pull request. A check refuses data files and runs the tests. Turn on the same check locally once per clone with `git config core.hooksPath .githooks`.
- Set up and test:

  ```
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  .venv/bin/python -m pytest tests
  ```

## Layout

- `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline, one module per stage (table above), plus `gsheets.py` (Google sign-in), `attendance.py` (the attendance model) and `textfix.py`.
- `prompts/`: the prompts for the Claude agents (cards, linking, drafts, global pass, critics, talk order, judge).
- `docs/`: how-to notes.
- `tests/`: pytest with made-up fixtures.
- `prototype/`: the first test on the 2026 superconducting sessions; reference only.
- `CLAUDE.md`: working instructions for Claude Code.

## License

MIT; see [LICENSE](LICENSE).
