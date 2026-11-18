# Runbook

The steps of a DQI sort, in order, with the command for each and what the lead decides. It is written for a new lead
working with Claude Code: say "run the DQI sort with dqi-sort's RUNBOOK.md" and Claude does the steps; you answer
at the checkpoints. [PROCESS.md](PROCESS.md) explains why each step is the way it is.

**At any point**, `python -m dqi_sort.status DATA_DIR` says which stages are done, what waits on you and the next
command. Every command runs from this repo (`.venv/bin/python -m dqi_sort.…`) with the year's private data folder
as its argument (`../dqi-2028` below).

Dates are from the 2027 run (meeting April 12-16, 2027), as a guide. In 2027 the abstracts arrived on Nov 5-7 and
APS took the sort back on Nov 18: about two weeks, most of it waiting for reviewers.

## Who does what

- **The lead** (the sorting lead or secretary): owns the data repo, decides at the checkpoints, talks to APS and the
  reviewers. About 1 to 2 hours a day in the two weeks, mostly reading Claude's summaries and answering.
- **The program chair**: the list of expected mini-symposium invited speakers and their topics (in 2027, a
  spreadsheet from the chair, Nov 5).
- **Reviewers**, one or two per review area (about 10 areas): review the area's sessions in a Google Sheet (a couple
  of hours a round, two or three rounds), then pick session chairs for their area.
- **Claude Code**: everything else. Agent steps (cards, linking, drafts, global pass, talk order) run as subagents in
  Claude Code on the lead's subscription; no API key.
- **APS**: the sorting sheet, the room grid, the volunteer-chair list, chair invitations and, in 2027, entering our
  schedule into its Summit Grid from our CSV.

## Set up (October)

1. **Install.** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; `git config core.hooksPath
   .githooks`; Ollama with `ollama pull embeddinggemma` ([docs/embeddings.md](docs/embeddings.md)). Google sign-in
   for Sheets: [docs/google_sheets.md](docs/google_sheets.md) (the lead's own Google account).
2. **Data repo.** `python -m dqi_sort.new_year ../dqi-2028 --from ../dqi-2027 --year 2028`. It copies last year's
   config with the yearly settings blanked ("TODO (new year)"), the attendance history and last year's program, and
   makes the first commit. Create the private GitHub repo in the `dqi-sorting` organization and push. Reviewers get
   read access as outside collaborators (Read role); only the lead pushes.
3. **Config.** Fill every "TODO (new year)" in `config.yaml` from APS's instructions and sorting sheet: meeting dates,
   division code (24 in 2027), the categories, the session targets, `aps_sheet.id` (APS's sorting sheet),
   `chair_volunteer_sheet.id`. Then `python -m dqi_sort.aps_input check ../dqi-2028`: it reads APS's sheet and lists
   tabs, columns, categories and anything the config does not expect. APS changes the sheet every year (in 2027 it
   went from six in-person tabs to one, mid-sort): fix `aps_sheet.tabs` and `aps_columns` until the check prints OK.
4. **Drive folder.** `python -m dqi_sort.gsheets setup ../dqi-2028 --folder "DQI 2028"` (review and chair sheets go
   there).
5. **Venue and grid.** When APS opens the grid (Summit Grid site, password from APS), write `venue/rooms.csv` (room,
   capacity, size class, recorded or not, APS room number) and `schedule/slots.csv` (our blocks: day, start, length,
   room, APS block code) and `schedule/symposia.csv`; see PROCESS.md, Venue intake, and last year's files in
   `history/<year>/`. Then set `room_sizes` and `size_cutoffs` in the config.
6. **Attendance.** If last year's RFID data came in, fold it into `history/attendance.csv` and refit (After the
   meeting, below) before scheduling.

## Week 1: abstracts to sort v1 (in 2027: Nov 5-8)

1. **Pull and intake.** `aps_input pull`, then `intake`. Each later round of APS changes is the same two commands,
   then `aps_input diff` to see what APS added, removed or changed.
2. **Invited speakers.** Reconcile the invited talks in APS's sheet against the chair's list (missing, unexpected,
   entered twice, no abstract). Expected topics for invited talks with no abstract go in `input/invited_topics.csv`;
   replacement speakers and affiliations in `input/overrides.csv` (config `invited_topics`, `overrides`).
   **Checkpoint:** the lead confirms; log it in `checkpoints.md`.
3. **Cards.** `cards prepare`, one Haiku subagent per batch (the prompt is `work/cards/agent_task.md`), `cards merge`,
   then `embed` ([docs/cards.md](docs/cards.md)). A late talk: `cards prepare --ids FILE` with just its ID.
4. **Linking.** `linking prepare`, one agent, `linking apply`: multi-part series, "put me with X" requests,
   institutions. **Checkpoint:** the lead confirms unsure links.
5. **Areas and flags.** `areas propose`, `areas flags`. **Checkpoint:** `views/flags.md` is the one list of talks
   the lead decides: offer to another unit (`decide offer UNIT TALK`), poster, keep, duplicate.
6. **Drafts and global pass.** `sessions prepare`, one Opus agent per area, `sessions check`; then `pack start`, the
   global-pass agent with `pack ops`, `pack critique`, `pack finish` ([docs/sessions.md](docs/sessions.md)). The
   virtual track is drafted here and is final. **Checkpoint:** the lead reads the packing report and merges.
7. **Overview.** `overview ../dqi-2028`: the whole sort on one page, for the lead and reviewers.

## Weeks 1-2: review rounds and chairs (in 2027: Nov 8-16)

1. **Send.** `sheets sync --all`: the shared sheet and one sheet per area; share each with its reviewers. Send the
   reviewers the instructions (in 2027 a short Google Doc: what to check, by when, how to reply).
2. **Read back** each returned area: `review read AREA` (report in `work/review/AREA-rN/`), then `review apply AREA`.
   Claude acts on the reviewer's notes with `review move`, easiest areas first, a commit per area. Moves that touch
   another area, or a decision about a talk leaving DQI, go to the lead. Then `sheets sync --all` for the next round.
   Two or three rounds.
3. **Each round, APS's sheet too:** `aps_input pull`, `intake`, `aps_input diff`. Talks other units take or send:
   `decide exchanged / returned / received`. Keep `open_questions.md` and the list for APS (`aps_email.md`) current.
4. **Chairs** (from round 2): `aps_input volunteers`, then `chairs sync` makes the recruiting sheet (a tab per area,
   suggested chairs by topic). Reviewers type a session code next to each chosen volunteer; `chairs sync` reads them
   back. Fill any left from the suggestions (lead's call). Virtual sessions need a chair and a co-chair: the lead
   picks them (`chairs/virtual.csv`).
5. **Virtual.** APS's virtual grid fills first: place the virtual sessions, submit them to APS, and lock them in
   `schedule/schedule.csv`.

## Schedule, talk order, delivery (in 2027: Nov 16-18)

1. **Schedule.** `schedule budget --apply` (room sizes from the attendance model; reviewers' size requests kept),
   `schedule solve`, `schedule check`. `schedule_page` writes the page to post for review (`--note` for a note to
   reviewers; `--no-numbers` for a copy to share outside the team). **Checkpoint:** the lead approves; room upgrades
   or swaps with `schedule swap`.
2. **Talk order.** Sessions whose invited talk must open the session (a reviewer's "keep these talks right after the
   invited talk") go in config `invited_first`. Then `order positions`, `order prepare`, one agent per area,
   `order apply`, `order check`.
3. **Validate.** `validate --delivery`: 0 errors before delivery.
4. **Deliver.** `aps_fill write` fills APS's sorting sheet (sessions, chairs, each talk's session and order; never the
   Virtual tab), then `aps_fill check` reads it back and compares it with git. Rerun both after any late change.
   Write the schedule for APS as a CSV (one row per session: day, time, block, room; `views/schedule_for_aps.csv` in
   2027) and send it with the `--no-numbers` schedule page; in 2027 APS entered it into the Summit Grid. Check APS's
   entry against `schedule/schedule.csv`.
5. **Late changes:** `late add / withdraw / move`, each committed and checked; then `aps_fill write` and `check`.

## After the meeting

- When APS sends the RFID export, add it to the data repo's `input/attendance/`, extend `history/build_attendance.py`
  to read it (match sessions with `history/<year>/`), rebuild `history/attendance.csv`, and refit:
  `python -m dqi_sort.attendance_report ../dqi-2028`.
- Write down what to change next year (feedback to APS, changes to this repo) while it is fresh.

## Things that cost time in 2027

- **The recording rule.** Mini-symposia must be in recorded rooms, and recorded slots barely covered them (46
  recorded 108-minute slots for 46 mini-symposia), so about ten had to become 108 minutes. Count recorded slots per
  length as soon as the grid is in.
- **Invited abstracts arrive late** (a quarter still missing at delivery). Sort them by the chair's expected topics.
- **Talks offered to other units** linger in APS's sheet; keep them placed in DQI until APS removes them.
- **`decide` and `late` commit the whole data repo**: commit or stash other edits first.
- **Reviewer moves** recorded with `review move` default to `--by claude`; pass `--by` with the reviewer's name.
- **A chair added by a reviewer** needs a name, email and affiliation, or APS's sheet shows the session incomplete.

## Cost

Agent work runs on the lead's Claude subscription. Measured in 2027: talk order, 9 Opus agents (one per area, 6 to 23
sessions each), about 80,000 to 125,000 tokens and 1 to 2 minutes each. One Haiku card agent for a single late talk:
about 65,000 tokens. The bigger stages (cards for about 1,900 talks, the drafts and the global pass) were not
measured; record them next year here.
