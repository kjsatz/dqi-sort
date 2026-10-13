You are drafting the sessions for one work area of the APS Global Physics Summit, Division of Quantum
Information (DQI). After all areas are drafted, a global pass fits the whole meeting to its time slots, combining
released talks from different areas and trading a few talks between sessions; then researchers who know the
field review it. Make the draft a program they would recognise as good.

## Input

Read `{DIR}/brief.md` (the area, its numbers and its limits), then every card in `{DIR}/cards.txt`. The file
is long: read it in chunks until you have seen every card. Read only these two files. Keep any helper scripts in `{DIR}/scratch/` (other agents run at the same time and share the
general scratchpad).

Each card is a standard summary of one talk: ID, type (oral or INVITED), title, speaker and institution, then platform,
problem, approach, key claim and keywords, and sometimes a series (multi-part talks, including pairs whose
submitter asked to follow another talk), a scheduling request from the submitter, a note that the talk could go to
another APS unit, or a bridge mark ("near SCMAT 7/10": most of its nearest neighbours by content are in other
areas). Cards are sorted by the DQI category that fits
them best, so neighbouring cards are often related, but categories do not matter; content does.

## Session rules

{RULES}
- **Series.** All parts of a series must be in the same session, consecutive, in part order.
- **At most 2 invited talks per session.** Put each invited talk in the session whose topic it fits best.
- **At most {MAX_INST} talks from one institution per session** (a soft rule; parts of a series count). Break
  it only when the topic leaves no reasonable alternative, and say so in `notes`.
- **Submitter requests.** Honour requests about grouping or order (e.g. "same session as my colleague's talk").
  Requests about days and times are handled at scheduling; ignore them here.

## What a good session is

A session is good if an attendee who walks in for its topic finds nearly every talk relevant: one community
and one question, not just shared vocabulary. Prefer sessions with a crisp theme to grab-bags. Group by
platform or device (e.g. fluxonium, cat qubits, NV ensembles) or by problem (e.g. readout, leakage,
decoding), whichever gives the more natural audience for that set of talks. When a topic has more talks than
one session holds, split it along a real seam (theory and experiment, junction physics and junction
fabrication) rather than arbitrarily, and make the halves' scopes clearly different. Order the talks so the
session flows: related talks adjacent, theory and experiment pairs together, series consecutive. Where an
invited talk goes in the order is decided later, at scheduling; put it where it fits best (usually first).

Titles are what people see in the program: short, specific, in title case, with no area codes or numbering
("Fluxonium Qubits", "Readout and Reset I" only if there really are two such sessions).

## Released talks

Release a talk when it fits poorly in every session you can build here: it belongs to another area's topic, or
it would only be filler. Released talks go to the pool of lonely abstracts, and the global pass places them across
all of DQI, often in a session drawn from several areas. When choosing what to release, prefer bridge talks
(marked "near ...") and talks marked "other unit": they are the most likely to find a good home with similar talks
from other areas. Never release a talk that fits a session here well, bridge mark or not. Most areas should release
under 5% of their units.

Each released talk needs a one-line reason and a suggested home (a session topic, and the area if it is
another one).

## Output

Write `{DIR}/proposal.json`:

```
{"sessions": [{"title": "Fluxonium Qubits",
               "scope": "One sentence: what belongs here (do not name other sessions; titles change).",
               "talks": ["id", "...in presentation order..."],
               "weakest_fits": ["up to 3 ids that fit least well, if any"]}],
 "released": [{"id": "...", "reason": "...", "suggested_home": "..."}],
 "notes": "Anything the reviewers should know: hard calls, rules you could not keep."}
```

`released` may be an empty list.

Then run

    {CHECK}

and fix every ERROR until it prints OK. Fix WARN lines where you reasonably can, and explain the rest in
`notes`.

Finish with a short summary (3 to 5 lines): number of sessions and their sizes, units released, and the hardest
calls.
