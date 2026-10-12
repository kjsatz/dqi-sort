You are proposing the sessions for one review area of the APS Global Physics Summit, Division of Quantum
Information (DQI). Researchers who know the field will review your proposal in a spreadsheet, so make it a
program they would recognise as good.

## Input

Read `{DIR}/brief.md` (the area, its numbers and its limits), then every card in `{DIR}/cards.txt`. The file
is long: read it in chunks until you have seen every card. Read only these two files.

Each card is a standard summary of one talk: ID, type (oral or INVITED), title, speaker and institution, then platform,
problem, approach, key claim and keywords, and sometimes a series (multi-part talks), a scheduling request from
the submitter, or a note that the talk could go to another APS unit. Cards are sorted by the DQI category that fits
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

Release a talk only when it fits poorly in every session you can build here and would fit better somewhere
else in DQI: another area's topic, or a session drawn from several areas. Released talks go to the pool of
lonely abstracts, and the next stage (packing) places them across all of DQI using the slots you did not use.
Release sparingly: most areas should release under 5% of their units. Never release a talk that has a
reasonable home here just to make the numbers work. Talks marked "other unit" are the first candidates
if something has to go, but keep them when they fit.

Each released talk needs a one-line reason and a suggested home (a session topic, and the area if it is
another one).

## Options

Where part of the area could be split in clearly different reasonable ways (for example by platform versus by
problem), you may add up to 3 alternatives. Each replaces specific sessions of your proposal with a different
set of sessions holding exactly the same talks. Give options only where the choice genuinely matters to the
reviewers; most areas need none or one.

## Output

Write `{DIR}/proposal.json`:

```
{"sessions": [{"title": "Fluxonium Qubits", "minutes": 144,
               "scope": "One sentence: what belongs here, and what goes to the nearest similar session.",
               "talks": ["id", "...in presentation order..."],
               "weakest_fits": ["up to 3 ids that fit least well, if any"]}],
 "released": [{"id": "...", "reason": "...", "suggested_home": "..."}],
 "options": [{"why": "...", "replaces": [3, 4], "sessions": [...same form as above...]}],
 "notes": "Anything the reviewers should know: hard calls, rules you could not keep."}
```

`replaces` lists session numbers, counting your `sessions` from 1. `options` and `released` may be empty lists.

Then run

    {CHECK}

and fix every ERROR until it prints OK. Fix WARN lines where you reasonably can, and explain the rest in
`notes`.

Finish with a short summary (3 to 5 lines): sessions by length, units released, and the hardest calls.
