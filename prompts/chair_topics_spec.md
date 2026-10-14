You are grouping the sessions of the APS Global Physics Summit, Division of Quantum Information (DQI), into chair
recruiting topics. A coordinator will invite volunteers to chair "a session on superconducting qubit readout", not a
specific session, so each topic must be a field a chair can recognise as theirs.

## Input

Read `{DIR}/sessions.md` in full: every in-person session with its ID, review area, title and scope. Read nothing
else. Keep any helper scripts in `{DIR}/scratch/`.

## Rules

- Every in-person session goes in exactly one topic.
- A topic holds 3 to 8 sessions (fewer only for a topic that is clearly its own field), usually within one review
  area. Aim for about 35 to 45 topics.
- Name each topic in plain words a volunteer would recognise, up to 6 words ("Superconducting qubit readout",
  "Quantum LDPC codes and decoding", "NV-center sensing").

## Output

Write `{DIR}/topics.json`:

```
[{"topic": "Superconducting qubit readout", "area": "SCDEV", "sessions": ["SCDEV28", "SCDEV30", "..."]}, ...]
```

Then run `{CHECK}` and fix every error until it prints OK. Finish with a 2 line summary.
