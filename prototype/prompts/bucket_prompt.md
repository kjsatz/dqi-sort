You are helping organize the superconducting-circuits portion of the APS Global Physics Summit
(Division of Quantum Information). Your job: turn one BUCKET of talks into conference sessions.

## Input
`{DIR}/cards.txt` (human-readable) and `{DIR}/cards.json` ({id: card}). Each card is a standardized
summary of one talk: id, type, title, platform, problem, approach, key claim, keywords, and
sometimes LINKED multi-part partners, scheduling constraints, or a maybe-other-unit flag.
Read ONLY these files plus `/home/claude/sessbuild/validate.py`. Do not open any other files.

The bucket was built from a submission category ("{BUCKET_NAME}") plus talks whose content suggests
that category as a first or second choice. So it OVERLAPS neighbouring buckets: some talks here
are peripheral and will be better placed in a session built from another bucket.

## Session rules
- An oral (contributed) talk is 12 min = 1 unit; an INVITED talk is 36 min = 3 units.
- Every session is exactly 15 units: 1 invited + 12 orals, 2 invited + 9 orals, or 15 orals.
  (13-14 units is tolerated only if unavoidable.)
- LINKED multi-part talks must go in the same session, consecutive, in the listed order.
  If a linked partner is not in this bucket, just keep the one you have and note it.
- Respect submitter constraints where possible (mention any you could not honor).

## What a good session is
A session is good if an attendee who walks in for its topic finds nearly every talk relevant:
same scientific community and question, not just shared vocabulary. Prefer sessions with a crisp
theme over grab-bags. Talks can be grouped by device/platform (e.g. a fluxonium session) or by
problem (e.g. readout, TLS) - whichever gives the more natural audience for that set of talks.
Each invited talk should anchor a session whose topic it fits well; put it where it best frames
the session (usually first). Order the orals so the session flows (related talks adjacent,
theory/experiment pairs together, multi-part talks consecutive).

## Task
1. Read all cards. Sketch the natural topical structure of the bucket.
2. Build as many full, coherent sessions as the core material supports (the bucket has about
   {UNITS} units, i.e. at most ~{MAXS} sessions; because of the overlap, fewer is normal).
3. RELEASE talks that are peripheral to this bucket (they will be placed from another bucket),
   and talks that would only fit as filler. For each, give a short reason and a suggested home
   (a session topic, e.g. "Josephson parametric amplifiers", or "outside superconducting area").
   Don't release so much that core sessions run short - fill sessions with the best-fitting talks.
4. Write `{DIR}/proposal.json`:
   {"sessions": [{"title": "...", "scope": "one sentence: what belongs here",
                  "talks": ["id", ...in presentation order...],
                  "weakest_fits": ["id", ...up to 3 ids that fit least well, if any]}],
    "released": [{"id": "...", "reason": "...", "suggested_home": "..."}],
    "notes": "anything the human organizers should know (constraints not honored, hard calls)"}
5. Run `python3 /home/claude/sessbuild/validate.py {DIR}/cards.json {DIR}/proposal.json`
   and fix every ERROR until it prints OK.

Finish with a 3-5 line summary: number of sessions, number released, and the hardest calls.
