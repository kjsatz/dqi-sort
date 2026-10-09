# DQI session sorting and scheduling

This is how we propose to sort the Division of Quantum Information (DQI) abstracts for the APS Global Physics Summit into sessions, schedule those sessions into rooms, and recruit chairs. Claude drafts each step. People decide at five checkpoints.

Principles:

- **People decide at checkpoints.** Claude produces drafts, options and flags. A named person approves before work moves on.
- **Two tracks.** The in-person meeting and the smaller virtual meeting are sorted separately (see [Virtual conference](#virtual-conference)). Everything below is the in-person track unless it says otherwise.
- **One DQI-wide sort with soft boundaries.** Talks are grouped by content, not by submission category. Review is split into 5–10 areas drawn along natural lines, but talks flow freely between areas.
- **All state is plain-text CSV in git.** Every change is a commit, so anyone can see what moved and why.
- **The code is public; the data is private.** Abstracts never go in the public repo.
- **Late changes are small, local edits.** Adding or withdrawing a talk touches only what it affects.

## Process

| Stage | Claude | People |
| --- | --- | --- |
| 0. Prepare | Builds `config.yaml`; turns the APS schedule into the venue files (see [Venue intake](#venue-intake)) | Provide the session format, the room list and distances, the room-time grid, the symposium schedule, invited-talk notes, the chair volunteer list and past attendance (see [Before abstracts arrive](#before-abstracts-arrive)) |
| 1. Intake | Parses the APS workbook (one in-person table and one virtual table), repairs text-encoding damage where it can (keeping the original), flags duplicates | — |
| 2. Presentation cards | Writes a standard card for each talk, one abstract at a time (Claude Haiku; see [Presentation cards](#presentation-cards)) | Spot-check a sample |
| 3. Linking | Looks across all talks at once: groups multi-part talks into series, and normalizes affiliations to institutions | Confirm uncertain links |
| 4. Routing and flags | Proposes 5–10 review areas and assigns each talk to one; lists talks flagged for leadership review, as candidates for another APS unit, or as malformed | **Checkpoint:** decide each flagged talk; adjust area boundaries |
| 5. Sessions per area | Proposes the sessions for each area. Where the split is obvious, one proposal; where it isn't, two to four options, each with fill and invited-talk placement | **Checkpoint:** each area's reviewers pick, comment on or edit the proposal in their review sheet |
| 6. Packing | Places leftovers across all of DQI, draws together related talks from different areas and categories to fill sessions, keeps sessions within the DQI session budget, orders talks, drafts titles. Opens a pull request with a report of every move and why | **Checkpoint:** lead reviews and merges the pull request |
| 7. Sort review | Generates the shared sheet and one area sheet per area; checks each returned sheet against the version sent, opens a pull request with the changes; finally places any remaining lonely abstracts | **Checkpoint:** reviewers edit their area sheet; lead merges the pull requests (see [Sort review](#sort-review)) |
| 8. Schedule | Estimates attendance for every session; proposes room trades with symposia; then a solver assigns sessions to room-time slots (see [Scheduling](#scheduling)) | **Checkpoint:** decide the trades; approve or adjust the schedule |
| 9. Talk order | Sets each room's invited-talk position and re-orders every session around it (see [Talk order](#talk-order)) | Spot-check |
| 10. Chairs (starts after stage 6, runs in parallel) | Links volunteers to their abstracts, builds the chair handoff sheet, reads back the coordinator's returns, matches confirmed chairs to sessions | Coordinator runs all correspondence and returns the sheet; lead approves the matches (see [Chairs](#chairs)) |
| 11. Deliver | Writes session names, order and chairs into the APS sheet; handles late adds, withdrawals and moves | Approve each late change |

After the meeting, we keep the final sort and the edits people made to Claude's drafts. They are the best input for improving the process next year.

## Presentation cards

Each talk gets a card, written by Claude Haiku from its title, abstract, submitter notes and affiliation. Cards are the common format every later step reads.

| Field | Contents |
| --- | --- |
| `platform` | The device or system the work is about (up to 8 words) |
| `problem` | The goal or question (up to 8 words) |
| `approach` | experiment, theory, simulation/modeling, fabrication/materials characterization, or methods/tooling |
| `key_claim` | One sentence on what was done or found (up to 30 words) |
| `keywords` | 3–6 specific technical terms |
| `best_category`, `runner_up_category` | The DQI submission categories the content fits best, whatever was submitted |
| `session_pitch` | A plausible title for the session the talk would sit in |
| `affiliation` | The affiliation as submitted (normalized to an institution in stage 3) |
| `multi_part` | If the talk says it is one part of a series: its part number, the number of parts, and words that identify the other parts |
| `constraints` | Scheduling requests from the submitter notes |
| `leadership_review` | Empty, or **Needs leadership review: may not meet the standard for an oral talk**, with a one-line reason |
| `other_unit` | Empty, or another APS unit the talk could go to, with a strength (`could fit` or `belongs there`) and a one-line reason |
| `malformed` | Empty, or a note that the text looks garbled or broken (for example unreadable characters from an encoding problem, or a cut-off abstract), with what seems wrong and a suggested fix if one is clear |

Malformed text is caught twice. Intake repairs common encoding damage automatically (for example Japanese or accented text turned into nonsense characters) and records what it changed. The card's `malformed` field catches what is left. Malformed talks go to the lead with a suggested fix; once fixed, the card is rebuilt.

Two kinds of association need all talks in view, so they are done in stage 3, not on the card:

- **Multi-part series.** Claude reads every talk with a `multi_part` entry together and assigns series IDs (`series`, `series_part` in `talks.csv`). Parts are often submitted to different categories, so matching uses titles, speakers and the card's hints, not the category. Uncertain links go to the lead.
- **Institutions.** Claude reads the full list of submitted affiliations once and maps each to one institution name, so "MIT" and "Massachusetts Institute of Technology" match.

The list of other APS units (divisions and topical groups, such as DAMOP, DCMP, GPMFC and GIMS) is kept in `config.yaml`. Moving a talk to another unit is a last resort. We use it when a talk clearly belongs elsewhere, or when a talk is left over and has nowhere good to go in DQI.

## Why options, and when

The sessions we need depend on which abstracts arrive and how they happen to group. Many topics can be split several reasonable ways. Then Claude proposes alternatives, and the people who know the field choose. When one split is clearly right, Claude proposes just that one.

Sessions must also be nearly full, because the session budget is fixed by the total talk count with almost no slack. Topics genuinely overlap across submission categories, so filling sessions often means drawing related talks together from different categories and areas. Packing does this explicitly, and the packing report lists every such move.

## Avoiding single-group sessions

A session should not feel like one group's meeting. Session proposals and packing treat this as a soft rule: try to keep any one institution to at most 4 talks per session (`max_same_institution` in `config.yaml`). Exceptions are listed in the packing report for the lead to accept or fix.

Institution is a proxy for research group. A large institution can host several unrelated groups, so reviewers can accept a flagged session. A multi-part series from one group still counts as several talks.

## Review areas

Review is split into 5–10 areas along natural lines. Areas should be roughly equal in size, but a small topic that is clearly its own thing can be a small area, and a large block of closely related talks (superconducting qubits, for example) can be a large one. Areas are for dividing the reviewing work; they are not walls, and talks move between them.

Each area holds enough talks to fill its sessions. Sessions are not all the same size: a 144-minute session holds 12 contributed talks and a 108-minute session holds 9, with an invited talk counting as 3. So fill is shown in minutes against each session's own length.

## Lonely abstracts

Any talk not currently in a session is a lonely abstract. Talks become lonely when packing leaves them over, when a reviewer kicks them out, or when they arrive late. The pool should stay small. It is shown to everyone on the shared sheet (below), which is regenerated every time a change is merged, so it is always current.

Near the end of review, one clean-up step empties the pool: Claude finds the best available home for each remaining lonely abstract (a session with room, or a small swap) and opens a pull request listing each placement and why. Moving a talk to another unit is a last resort here too. The pool must be empty at delivery.

## Sort review

Reviewers get two kinds of Google Sheet, both generated from the CSVs in git.

**Shared sheet (read-only, everyone).** The whole sort as it stands:

- **Session summary:** every session with its title, area, length and fill.
- **Sessions:** every talk, grouped by session in order.
- **Lonely abstracts:** every talk not in a session, with its summary.
- **Moves:** a running ledger of every talk moved into or out of the lonely pool, between areas, to or from another APS unit, and every new talk added.

**Area sheet (editable, one per area).** Just that area's part:

- **Session summary:** one row per session, with session ID, title, length, minutes filled (computed) and human notes.
- **Sessions:** one row per talk, with session ID, order, talk ID, title, speaker, institution, one-line summary, a **Move to lonely abstracts** checkbox and human notes.

What reviewers do:

- reorder talks
- edit session titles
- check the box to kick a talk out
- copy in talks from the shared Lonely abstracts tab
- copy in a talk from another area, after agreeing it with that area (on Slack)

Anything else goes in the human notes, such as "this should follow talk 1234".

### How sheets and git stay in step

`sync-sheets` runs automatically on every merge to the private data repo (a GitHub Action, with Google credentials stored as a secret of that repo, never in the public code repo). It does two things:

- **Updates the shared sheet in place.** Nobody edits it, so this is safe.
- **Makes a new area sheet for each area that was checked in** since the last run. Area sheets are never changed while a reviewer has them; each round gets a fresh copy, named with its area, round and commit. A talk that moves away in the meantime shows up in the shared Moves ledger, but the reviewer's own sheet is left alone.

Every sheet is stamped with the commit it was generated from, in a header row and in the file description, e.g. "Generated from git 50de1a, 12 Nov 14:03".

### Sheet style

Simple and readable:

- a title row with the area, round and stamp, then a frozen, bold header row
- each session's rows in a light alternating band, with invited talks in bold
- titles wrapped and column widths set, so nothing is cut off
- the Move to lonely abstracts column as real checkboxes
- fill shown as minutes used of the session's length, shaded when a session is under-filled
- human notes columns lightly tinted, so it's clear where to type

### New talks

The lead adds a new talk (a late submission, or one transferred from another unit) with one command (`add-talk`). It goes into the lonely pool or straight into a named session. A card is built for it, the ledger records it, and it appears on the next generated sheets. To put it into an area sheet that is already out, the lead can paste the row in; intake recognizes it as a new talk.

### Intake

When an area sheet comes back, Claude compares it with the version that was sent (its stamped commit) to work out what the reviewer changed. It then applies only those changes to the current state of the sort. This three-way comparison is what lets several areas work at once.

Checks before anything is applied:

- **Nothing missing.** Every talk that was sent is still in a session or checked for the lonely pool.
- **Every added talk is accounted for.** A talk copied in from the lonely pool is removed from the pool. A talk copied in from another area is removed from that area, and the pull request says where it came from. A brand-new talk must already be in `talks.csv` (via `add-talk`).
- **Conflicts are flagged, not guessed.** Two cases count as conflicts. One is when a talk this reviewer changed was also moved by someone else since the sheet was made. The other is when two areas both copied in the same talk. Either way, the first merged change stands and the pull request lists the conflict for the lead.
- **Knock-on gaps are reported.** If a talk was taken from an area, that area's next sheet shows the gap. Its review pull request also notes the gap, in case the session needs topping up.

Claude then applies the changes, interprets the human notes, and opens one pull request per returned sheet. The pull request lists every change, every move between areas, every conflict, and any note it could not act on. Human notes are kept in git (`sorting/notes.csv`).

Every applied move is appended to the ledger (`sorting/moves.csv`).

Session proposals in stage 5 use the same area sheets, with an extra Options tab where an area has alternative splits. Leadership-review and other-unit flags go to the lead, not to the area sheets.

## Packing report

Packing changes the whole sort at once, so it arrives as a GitHub pull request. The description lists:

- each talk that moved, with where it moved from and to, and a one-line reason
- talks drawn into a session from another area or category
- each session's fill
- any session with more than one empty talk slot. Session lengths are not fixed in advance: a 144-minute session with three empty slots is a full 108-minute session. So packing picks each session's length to keep it full, within the number of 144- and 108-minute slots available (roughly half of each), and the report shows how many sessions of each length were built against the slots for each
- any session with more than the allowed talks from one institution
- the total against the session budget
- any talk proposed for another unit, as a last resort

The lead reads the report, comments on the pull request, and merges it when it's right.

## Data

The data repo holds one set of files per year:

| File | One row per | Columns |
| --- | --- | --- |
| `config.yaml` | — | Division number, session lengths (144 and 108 minutes in person this year; 120 virtual), talk lengths (12 and 36), session budget, DQI submission categories, other APS units, APS column layout, scheduling weights |
| `talks.csv` | talk | talk_id, track (in_person / virtual), type, minutes, title, speaker, affiliation, institution, submitted_category, area, series, series_part, time_windows (virtual only), status, flags, notes |
| `abstracts.jsonl` | talk | talk_id, title, body, submitter_notes (repaired text), raw (the text as received, when a repair was made), text_fix (what was changed and by whom) |
| `cards.jsonl` | talk | Presentation card as JSON |
| `institutions.csv` | submitted affiliation | affiliation, institution |
| `embeddings/<model>__<recipe>.npz` | talk | Embedding vectors (NumPy, float16); see `docs/embeddings.md` |
| `sorting/sessions.csv` | session | session_id, title, kind (contributed / focus / symposium), minutes (144 or 108), area, locked, notes |
| `sorting/assignments.csv` | talk | talk_id, session_id (blank for lonely abstracts), order, locked, note |
| `sorting/moves.csv` | move | when, commit, talk_id, from (session, area, lonely, new, or another unit), to, by, reason |
| `sorting/notes.csv` | human note | round, area, reviewer, talk_id or session_id, note, resolution |
| `venue/rooms.csv` | room | room_id, name, capacity, size (small / medium / large), zone, invited_block_144, invited_block_108 |
| `venue/room_distances.csv` | pair of rooms | room_a, room_b, walk_minutes (rough) |
| `schedule/slots.csv` | room-time slot | slot_id, track, day, start, end, minutes, room_id (blank for virtual) |
| `schedule/schedule.csv` | session | session_id, slot_id, locked |
| `history/attendance.csv` | past session | year, session_code, session_title, kind (contributed / focus / symposium), room_id, capacity, count |
| `chairs/volunteers.csv` | volunteer | volunteer_id, name, email, affiliation, chair_mode (in_person / virtual / both), presenting_mode, talk_ids (semicolon-separated), match_note |
| `chairs/returns.csv` | volunteer | volunteer_id, status, topics, unavailable, note (format below) |
| `chairs/chairs.csv` | session | session_id, volunteer_id |
| `chairs/invite_template.md` | — | **TODO (lead):** optional invitation text with fields `{name}` and `{topic}` |

Rules:

1. Session IDs are short and stable (`RDOUT1`, `TA`). Titles can change freely.
2. Files are sorted by their stable ID, so moving a talk changes one line.
3. Talks are never deleted. Their status becomes `withdrawn`, `poster` or `other_unit`.
4. `locked=true` means automation will not move it. Reviewers lock what they have decided.
5. A check runs on every commit:
   - every active talk is in exactly one session or in the lonely pool (the pool must be empty at delivery)
   - sessions are within capacity
   - multi-part talks are consecutive
   - each session fits the length of its slot
   - invited talks start on a 36-minute boundary
   - no speaker is double-booked
   - the session count is within budget
6. Alternative splits are files under `sorting/options/<area>/`. Picking one is a single commit.
7. Generated views (`views/sessions.md`, `views/schedule.md`, an interactive topic map) are for reading only. Nobody edits them.

Room distances can be rough, and pairs may be left out. A missing pair counts as near if both rooms are in the same zone and far otherwise. A first version can be just `rooms.csv` with zones.

## Scheduling

**The grid.** Each day has a fixed pattern of session times. This year, Monday to Thursday each have four sessions (144, 108, 144 and 108 minutes) and Friday has three (144, 108, 144). Most rooms are ours for every session time all week; a few rooms are available only for some. The invited symposium sessions arrive already scheduled; they are entered as locked sessions in their slots. `slots.csv` lists every room-time slot we have.

Hard rules:

- every session gets exactly one slot, of its own length (packing builds as many 144- and 108-minute sessions as there are slots of each)
- no speaker is in two places at once
- submitters' day constraints are honoured where possible
- confirmed chairs are not scheduled against their own talks or stated unavailability (if returns are in)

Preferences, with weights set in `config.yaml`:

- expected attendance fits the room
- similar topics do not run at the same time
- a theme does not run too many sessions in a row
- each room keeps a coherent identity
- related sessions held back to back are in rooms physically close to each other (short walk between them)

Expected attendance comes from past RFID counts in `history/attendance.csv`. A count that reached room capacity is treated as a lower bound, because a full room hides the real demand.

**Room trades with symposia.** Right before sessions are assigned to rooms, we decide deliberately whether to trade rooms with any symposia:

1. Claude estimates the expected attendance of every session, ours and the symposia, from the past two years of RFID counts and the topics.
2. It lists symposia likely to draw fewer people than their room holds, and our sessions likely to draw more than the rooms they would otherwise get.
3. It proposes trades: a symposium moves to a smaller room and one of our sessions takes its larger room.
4. The lead decides which trades to ask APS for. The trades are recorded in `schedule/schedule.csv` before the solver runs.

Symposia stay in medium or large rooms, never small ones. Last year's room sizes were roughly small 144, medium 288 and large 500; the size classes are set in `rooms.csv`.

## Venue intake

The schedule spreadsheet APS gives us is hard to read, so turning it into our venue files is an early, hands-on step between the lead and Claude. Claude reads the spreadsheet and proposes the files; the lead checks and corrects them, and anything unclear is resolved together. The result:

- `venue/rooms.csv`: every room we can use, with capacity and zone
- `venue/room_distances.csv`: rough walking times, as far as they are known
- `schedule/slots.csv`: every room-time slot that is ours
- `schedule/schedule.csv`: the symposia and anything else already assigned, locked

This step is done once, before sorting starts, and revisited only if APS changes the grid.

## Talk order

Invited talks should not all open their sessions. If each room puts its invited talk at a different point, attendees can move between rooms to catch several.

Sessions are built from 36-minute blocks: one invited talk or three contributed talks. A session has 0 or 1 invited talks (occasionally 2). This year there are two lengths:

| Session length | Blocks | Invited talk can be talk number |
| --- | --- | --- |
| 144 minutes | 4 | 1, 4, 7 or 10 |
| 108 minutes | 3 | 1, 4 or 7 |

After the schedule is approved:

1. **Room positions.** Each room gets an invited-talk block for its 144-minute sessions and one for its 108-minute sessions (`invited_block_144`, `invited_block_108` in `rooms.csv`). The positions are chosen so that rooms running at the same time, especially nearby rooms and similar topics, stagger their invited talks. The lead can also set them by hand.
2. **Re-order.** Claude re-orders each session with the invited talk fixed in its room's block. It does not just rotate or slide the invited talk into place; it rethinks the order so the session still flows. Talks that set up the invited talk come before it, follow-ups come after, and multi-part talks stay consecutive and do not straddle it. Submitters' "after X" requests still hold.
3. **Check.** The validator confirms that every invited talk starts on a 36-minute boundary and that every session fits its slot. Changes go into `sorting/assignments.csv` as one commit with a short note per session.

## Virtual conference

The virtual meeting is a separate, much smaller track: about 30–40 talks last year. It is sorted on its own and treated as its own area in review and in the chair handoff.

- **Sessions** are 120 minutes: 10 contributed talks, or an invited talk in place of 3 of them (rare).
- **Time zone comes first.** Submitters pick one or more of the virtual time windows that work for them (listed in Mountain Time). When a submitter gives none, we infer a window from their affiliation's location. Talks are grouped so that every speaker in a session can make the session's window, then by topic as far as the time zones allow.
- **Scheduling** places each virtual session in a virtual slot that all its speakers can make.
- **Chairs:** two confirmed chairs per session, preferably virtual presenters (see [Chairs](#chairs)).

## Chairs

One person, the chair coordinator, runs all chair correspondence from a single handoff sheet. Recruiting is by topic, not by session, because session times are not set yet.

1. **Link volunteers to abstracts.** APS sends one volunteer list for all of APS, with an in-person tab and a virtual tab. We keep the rows whose sub-category starts with our division number (17 in 2026; set as `division_code` in `config.yaml`). Each row carries the volunteer's abstract ID, which links them to their talk; we also match by name and email to find any other abstracts they have. Uncertain matches are flagged for the lead to confirm. The rows also say how the volunteer wants to chair (in person, virtual or both) and how they are presenting their own talk.
2. **Build the handoff.** After packing (stage 6), the preliminary sort gives the number of sessions in each rough topic, such as "superconducting qubit readout". The handoff is one Google Sheet with three tabs:
   - **Topics:** each topic, its area, its number of sessions, and how many chairs it needs (sessions plus a few backups). The virtual conference is one topic of its own and needs two confirmed chairs per session.
   - **Volunteers:** name and contact details from the APS volunteer list, their abstract IDs and titles, and a suggested topic. Optionally, a pre-filled invitation from `chairs/invite_template.md`. The return columns are empty.
   - **How to fill in:** the return format below and its allowed values.
3. **Coordinator recruits.** The coordinator writes to volunteers, offering a topic rather than a session. Invitations ask for scheduling constraints and promise we will not schedule chairs against their own talks. Nothing is sent automatically.
4. **Return.** The coordinator fills in the return columns. A sync command reads them into `chairs/returns.csv`.
5. **Match.** Confirmed chairs are matched to specific sessions in their topics. A chair is never placed against any of their own talks or their stated unavailability. Where possible a chair is not also a speaker in the session they chair, but such volunteers are still listed as options. The lead approves the matches, and the coordinator tells each chair their session.

**In-person and virtual chairs.** In-person sessions get chairs who are presenting in person; virtual sessions get chairs who are presenting virtually, preferably people who submitted to the virtual conference. In-person attendees can chair virtual sessions, but we keep the two groups separate unless we run short.

**Return format** (one row per volunteer, to be agreed with the coordinator before recruiting starts):

| Column | Values |
| --- | --- |
| `volunteer_id` | Pre-filled; do not change |
| `status` | `confirmed`, `declined` or `no reply` |
| `topics` | One or more topics from the Topics tab, separated by `;` |
| `unavailable` | Days or half-days they cannot chair, e.g. `Mon AM; Thu`; blank if none |
| `note` | Anything else, in free text |

**Timing.** Ideally the returns arrive before scheduling (stage 8), so chairs' unavailability goes into the solver as a hard rule. If they arrive later, we schedule anyway, since collisions are rare, and resolve any clash during matching by choosing another session in the chair's topic.

## Before abstracts arrive

- [ ] Process the past two years' RFID counts into `history/attendance.csv`
- [ ] Room list with capacities and zones (`venue/rooms.csv`), then rough walking distances when the floor plan is known
- [ ] Room-time grid and symposium schedule from APS
- [ ] Session lengths (144 and 108 minutes) and how many slots of each length, into `config.yaml` and `slots.csv`
- [ ] Virtual time windows and slots, and this year's division number (24?)
- [ ] DQI submission categories and the list of other APS units, into `config.yaml`
- [ ] Reviewers for each area (areas are drawn in stage 4)
- [ ] Last year's full workbook with the final sort, for a dry run
- [ ] Chair volunteer list format from APS (last year's as an example)
- [ ] Chair return format agreed with the coordinator
- [ ] Optional chair invitation template (`chairs/invite_template.md`)

## Roles

- **Lead:** runs the pipeline, decides flagged talks and routing, merges the packing pull request, approves the schedule.
- **Area reviewers:** choose session proposals; reorder, retitle and annotate their area sheet; kick out talks or take in lonely ones or (by agreement) talks from other areas.
- **Chair coordinator:** runs all chair correspondence from the handoff sheet and fills in the returns.

## Tools

- **Public repo:** parser, prompts, validators, solvers, embedding and map scripts, review-sheet generator.
- **Private repo:** one per year, holding the data above.
- **Claude Haiku via the API:** presentation cards. Under $1 for 5,000 talks.
- **Claude Opus via Claude Code:** linking, session proposals, packing, packing report, talk order and review.
- **Local embedding model:** for the topic map and the weak-fit checks. Free; nothing leaves the machine.
- **OR-Tools:** packing and schedule solvers.
- **Google Sheets API (service account):** `sync-sheets`, run by a GitHub Action in the private repo.

Speaker names are not sent to Claude for the cards; affiliations are, for the single-group rule.
