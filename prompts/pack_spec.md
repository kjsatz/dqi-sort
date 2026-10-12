You are doing the global pass for the sessions of the APS Global Physics Summit, Division of Quantum Information
(DQI). Agents drafted sessions area by area. Your job is to make the whole in-person program fit its time slots, and
to place the talks the drafts released, with all of DQI in view.

## Input

Read these files in `{DIR}/` in full (overview.md is long: read it in chunks until you have seen all of it):

- `overview.md`: every session (ID, units, the length the check currently gives it, what it needs, title, scope,
  talks with type, title, institution and series), then the pool of released talks with their full cards and the
  reason each was released.
- `check.md`: the length check (the same summary that heads overview.md).
- `candidates.md`: short lists from the card embeddings: for each pool talk the nearest sessions and pool talks; for
  each session that must grow, nearby sessions with talks to spare; for each that must shrink, its least-fitting
  talks; and the least coherent sessions. They are pointers, not answers.
- If `{DIR}/critique/*/suggestions.json` exist and the check says round 2 or later, read every one: independent
  critics' suggestions for this round (see below).

Read nothing else. Write only files under `{DIR}/ops/`. Keep any helper scripts in `{DIR}/scratch/` (other agents run at the same time and share the
general scratchpad).

## The rules

- An oral talk is 1 unit (12 minutes), an invited talk 3 units (36 minutes). A 144-minute session holds 12 units
  (11 allowed), a 108-minute session 9 (8 allowed). The check chooses each session's length to need the fewest
  moves, given how many slots of each length there are, and lists the sessions that must grow or shrink.
- The sort fits when no session must grow or shrink, there are no more sessions than slots, and the pool is empty.
  A talk may stay out of every session only if it has no reasonable home in DQI: `hold` it with a reason, for the lead.
- Series move as a block (moving one part moves all, in order). At most 2 invited talks per session. At most
  {MAX_INST} talks from one institution per session (soft).

## How to work

1. **Place the pool.** Where several pool talks belong together (with bridge talks from nearby sessions if
   needed), build a new session (`new`) of 8 to 12 units with a crisp theme. Otherwise move each pool talk into the
   session where it fits best, ideally one that must grow.
2. **Fit the lengths.** Close the remaining gaps with the most topical moves: move talks from sessions with spare
   units into nearby sessions that must grow, moving three talks (or an invited talk) to turn a session from one
   length into the other where that helps; merge two thin sessions or split a fat one if the topic has a real seam;
   `dissolve` a session only if its talks all have better homes.
3. **Keep the drafts' good structure.** Do not move a talk without a reason a reviewer would accept. Fewer, better
   moves beat many small ones. Edit a title or scope when a session's content changes.
4. **In round 2 and later**, weigh each critic suggestion: apply those that make a session clearly better and keep
   the sort fitting (a suggestion that breaks the fit needs a compensating move); skip the rest. Note in your
   summary which you applied and which you skipped, and why for the notable ones.

Write each batch of moves as a JSON list to `{DIR}/ops/round<R>_<NN>.json` and apply it with

    {PACK} ops {DATA} {DIR}/ops/round<R>_<NN>.json

Each op needs a one-line `reason`; the reasons go into the packing report the lead reads. The ops are:

```
{"op": "move", "talk": "ID", "to": "SESSION or pool", "position": 3, "reason": "..."}   position is optional (1-based)
{"op": "new", "title": "...", "scope": "One sentence.", "talks": ["ID", "..."], "reason": "..."}
{"op": "dissolve", "session": "SESSION", "reason": "..."}
{"op": "edit", "session": "SESSION", "title": "...", "scope": "...", "reason": "..."}
{"op": "order", "session": "SESSION", "talks": ["the same IDs in a new order"], "reason": "..."}
{"op": "hold", "talk": "ID", "reason": "..."}
```

The command prints the new check and rewrites overview.md, check.md and candidates.md; reread what you need.
`{PACK} status {DATA}` prints the check. Repeat until the check says FITS.

Finish with a short summary: sessions built, talks moved, talks held, the hardest calls, and anything the lead
should look at.
