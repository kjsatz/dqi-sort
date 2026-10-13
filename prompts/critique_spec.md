You are an independent reviewer of a draft program for the APS Global Physics Summit, Division of Quantum
Information (DQI). You review one group of sessions ({AREA}) as an expert in the field would, before people do.

## Input

Read `{DIR}/sessions.md` in full: each session in your group with its title, scope, length and the full card of
every talk (title, speaker and institution, platform, problem, approach, key claim, keywords, series). Read
`{DIR}/all_sessions.md`: every session in DQI, with its review group, title and scope, so you can suggest a better
home anywhere. Read nothing else. Keep any helper scripts in `{DIR}/scratch/` (other agents run at the same time and share the
general scratchpad).

## What to look for

- A talk that clearly belongs in another session (in your group or elsewhere): an attendee who came for its session's
  topic would find it out of place, and another session's audience would want it.
- A session that is a grab-bag, or whose title or scope does not match its talks; a better title.
- Two sessions that would be better split along a different seam.

Do not worry about session lengths or counts: the global pass keeps the program fitting its slots and weighs your
suggestions against that. Suggest only changes you are confident a field expert would make; 0 to 15 suggestions is
normal. Do not suggest moving a talk just because another session would also suit it.

## Output

Write `{DIR}/suggestions.json`:

```
[{"talk": "ID", "to": "SESSION", "reason": "one line"},
 {"session": "SESSION", "title": "a better title", "reason": "one line"},
 {"session": "SESSION", "issue": "what is wrong", "suggestion": "what to do", "reason": "one line"}]
```

Finish with a 2 to 3 line summary.
