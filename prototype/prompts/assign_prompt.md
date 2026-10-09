You are helping place talks into an already-designed set of conference sessions for the
superconducting-circuits portion of the APS Global Physics Summit.

## Input
- `{DIR}/plan.txt`: the 43 sessions (code, title, scope with boundaries, invited anchor talks).
- `{DIR}/assign/batch_{K}.txt`: {N} oral talk cards to place (standardized summaries).
Read ONLY these two files. Do not open any other files.

## Task
For EVERY talk in the batch, judge which sessions it fits, using the session scopes (not just
titles). Give 1-3 choices, best first, each with a fit score:
- 3 = core: squarely within the scope; the session's audience came for talks like this
- 2 = good: clearly relevant to that audience, but not the center of the scope
- 1 = acceptable: a reasonable home if space forces it, but peripheral
Give a second and third choice whenever one is at least acceptable (they let a later step
balance session sizes). LINKED multi-part talks must get identical choices.
If no session is even acceptable, give the closest one with fit 1 and say so in "note".

Write `{DIR}/assign/batch_{K}.out.json`: a JSON array with one object per talk, same order:
{"id": "...", "choices": [{"code": "S07", "fit": 3}, {"code": "S06", "fit": 2}], "note": ""}
("note": optional, <= 15 words, only for hard calls). Check with a short python script that
the file is valid JSON, has exactly {N} entries with the batch's ids, and that every code exists
in plan.txt. Finish with one line: how many talks had a fit-3 choice.
