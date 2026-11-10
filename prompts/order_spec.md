You are setting the talk order of sessions for the APS Global Physics Summit, Division of Quantum Information (DQI),
area {AREA}. The sessions are final; only the order within each changes.

## Input

Read `{DIR}/sessions.md` in full: each session in this area that holds an invited talk, with its length, slot and room,
the block where its invited talk must start, and every talk's card in the current order. Read nothing else. Keep any
helper scripts in `{DIR}/scratch/`.

## The rules

- Sessions are built from 36-minute blocks: one invited talk (36 minutes) or three contributed talks (12 minutes
  each). Block k starts at talk number 3(k-1)+1 when the talks before it are contributed: talk 1, 4, 7 or 10.
- The invited talk starts the block given for its session. Put exactly the right number of contributed minutes before
  it (36 per block). A session with two invited talks puts the other at another block start.
- Parts of a series stay consecutive, in part order, and do not straddle the invited talk.
- Submitters' order requests ("after X", "before Y") hold, and so do the area reviewer's notes listed under a session
  ("keep the Penn talks with Sigillito's invited talk", "Savytskyy right after Carter").

## What a good order is

Do not just slide the invited talk into place: rethink the order so the session flows. Talks that set up the invited
talk (background, earlier work, the same system) come before it; follow-ups and applications come after. Related
talks sit next to each other; theory and experiment on the same system pair up. The session should read as a story
to someone who stays for all of it.

Talks from the same institution or group on related topics sit together as a block, and a group whose invited talk is
in the session usually follows it directly (the invited speaker's students and collaborators right after them). When
the invited talk must move to reach its block, move its group with it rather than splitting the group. The current
order is usually the area reviewer's: keep its blocks and change it only as much as the invited talk's block and the
rules require. The check prints WARN lines for split institution groups: fix them unless a rule or a note forces the
split.

## Output

Write `{DIR}/order.json`: `{"SESSION_ID": ["talk_id", "... every talk of the session, in the new order"], ...}` for
every session in sessions.md. Then run

    {CHECK}

and fix every ERROR until it prints no errors. Finish with a 2 to 3 line summary.
