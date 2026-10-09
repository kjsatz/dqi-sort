You are the lead organizer for the superconducting-circuits portion of the APS Global Physics
Summit (Division of Quantum Information). Your job in this step: design the SESSION PLAN.

## Input
`{DIR}/cards.txt`: 567 talk cards (530 orals, 37 invited), each a
standardized summary: id, type, title, speaker, platform, problem, approach, key claim, keywords,
sometimes LINKED multi-part partners, submitter constraints, or a maybe-other-unit flag.
`{DIR}/invited_cards.txt` repeats just the 37 invited cards.
Read ONLY these files and `/home/claude/sessbuild/validate_plan.py`. Do not open other files.
Read the whole of cards.txt (it is long - read it in chunks until you have seen every card).

## Constraints
- Exactly 43 sessions. Each is 15 units: oral = 1 unit (12 min), invited = 3 units (36 min).
  A session holds 1 invited + 12 orals, 2 invited + 9 orals, or 15 orals.
- Every invited talk anchors exactly one session (max 2 per session). Invited talks are the
  sessions' anchors, so put each one in the session whose topic it fits best.
- Total oral capacity will be 645 - 3*37 = 534 for 530 orals: there is almost no slack, so
  the plan must match the real distribution of topics in the talks. Estimate how many orals
  will fit each session (`est_orals`); the estimates should add up to ~530 and no session can
  exceed its capacity (12 with one invited, 9 with two, 15 with none).
- Nothing can be dropped. Talks flagged maybe-other-unit still need a home here (a mixed
  "other topics" session is acceptable if needed, but keep it to at most one).

## What a good plan is
Each session should be something an attendee would choose to sit through: one community and
question, not just shared vocabulary. Group by device/platform (e.g. fluxonium, cat qubits,
TWPAs) or by problem (readout, TLS, quasiparticles), whichever gives the more natural audience
for that set of talks. When a topic has more talks than one session holds, split it along a
real seam (e.g. theory vs experiment, junction physics vs junction fabrication) rather than
arbitrarily, and make the two halves' scopes clearly distinct. Submission categories don't
matter; content does.

## Output
Write `{DIR}/plan.json`:
{"sessions": [{"code": "S01", "title": "session title as it would appear in the program",
   "scope": "2-3 sentences: what belongs here, and what does NOT (boundary with the nearest
             neighbouring sessions, naming them by code)",
   "invited": ["id", ...0-2 ids...], "est_orals": n,
   "family": "short name of a group of related sessions, e.g. 'readout & amplifiers'"}],
 "notes": "anything organizers should know"}
Use 6-8 families of roughly 4-9 sessions each (families will be reviewed together later).
The scopes are what a later step will use to assign every oral talk, so write them to
discriminate between similar sessions.

Run `python3 /home/claude/sessbuild/validate_plan.py {DIR}/cards.json {DIR}/plan.json`
and fix every ERROR until it prints OK. Finish with a short summary (families and session titles).
