# Session proposals

Stage 5 of `PROCESS.md`. Claude proposes the sessions for each review area, one agent per area, following `prompts/session_spec.md`. The agents run as Claude subagents inside Claude Code (Opus), not through the API. Code: `dqi_sort/sessions.py`.

## Steps

1. `python -m dqi_sort.sessions prepare DATA_DIR` splits the in-person grid (`schedule/slots.csv`) into a share for each area: at most so many 144-minute and 108-minute sessions, in proportion to the area's talks, adding up to every slot in the grid. For each area it writes `DATA_DIR/work/sessions/AREA/`: `cards.txt` (a compact card per talk, sorted by best category), `brief.md` (the area's numbers and share), `prompt.md` (the spec, filled in) and `talks.json` (what the check needs).
2. In Claude Code, launch one Opus subagent per area (they run in parallel), each told: "Read `DATA_DIR/work/sessions/AREA/prompt.md` and do exactly what it says. Read only the files it names. Write only proposal.json in that folder." Each writes `proposal.json` and runs `python -m dqi_sort.sessions check` on it until it prints OK.
3. `python -m dqi_sort.sessions apply DATA_DIR` checks every proposal and writes the sort: `sorting/sessions.csv`, `sorting/assignments.csv` (released talks have no session: they are the lonely abstracts), `sorting/moves.csv` (one row per release), alternative splits in `sorting/options/AREA/`, and the views `views/sessions.md` (the whole picture against the grid) and `views/sessions/AREA.md` (each session with its talks, estimated attendance and suggested room size). Ollama must be running for the attendance estimates; `--no-attendance` skips them.
4. Commit the data repo. `work/` is not committed. `prepare` refuses to run while proposals are in `work/sessions/`; move them away to start again.

Session IDs are the area code and a number (`QEC07`); they stay fixed when titles change.

## What the check enforces

- every talk of the area placed once or released with a reason and a suggested home
- sessions of 144 or 108 minutes, full to within one 12-minute unit; no more of each length than the area's share
- at most 2 invited talks per session; series together, consecutive and in part order
- virtual: 120-minute sessions whose speakers share a time window (the agent records the window it assumed for speakers who gave none)
- warnings: more than 4 talks from one institution in a session; more than 8% of an area's units released

Released talks and the slots the areas left unused go to packing (stage 6), which builds sessions from them across areas.
