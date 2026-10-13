You are an expert in quantum information science judging conference sessions for the APS Division of Quantum
Information (DQI). You will rate {N} sessions. They come from different sorts of the same abstracts; you are not told
which, and it does not matter: judge each session on its own.

## Input

Read `{DIR}/sessions.md` in full. Each session lists its talks: ID, title and a one-sentence summary of what the talk
does ([invited] marks a longer invited talk). Session lengths differ; judge coherence, not length. Read nothing else.
Keep any helper scripts in `{DIR}/scratch/`.

## Rate each session

The question: would an attendee who came for this session's topic find nearly every talk relevant (same community,
same question), as opposed to talks that merely share vocabulary?

- 5: one crisp theme; every talk clearly belongs.
- 4: a clear theme; one talk is a weak fit.
- 3: a recognisable but broad theme; two or three weak fits.
- 2: partly a grab-bag; several talks belong elsewhere.
- 1: no coherent theme.

List the IDs of talks that are clearly out of place (an expert would move them to a different session), and name
the theme in a few words.

## Output

Write `{DIR}/ratings.json`:

```
[{"session": "J01", "rating": 4, "out_of_place": ["ID"], "theme": "fluxonium readout"}, ...]
```

One entry per session, all {N}. Finish with one line: the number of sessions rated.
