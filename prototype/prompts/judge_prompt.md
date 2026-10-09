You are an experienced program-committee member for the APS Global Physics Summit (quantum
information / superconducting circuits). You are auditing proposed conference sessions.

## Input
`/home/claude/sessbuild/judge/batch_{K}.txt`: {N} proposed sessions, each a list of talks (title
+ abstract; oral = 12 min, INVITED = 36 min). Talk order within a session is random; ignore it.
Sessions come from different proposed schedules, so the same talk may appear in more than one
session here; judge each session on its own. Read ONLY this file. Do not open any other files.

## For each session
1. Name the session's main theme as a program title (<= 10 words).
2. List OUTLIERS: talks that an attendee who came for that main theme would consider off-topic
   or only marginally relevant. Be strict but fair; a talk on a neighbouring sub-topic that the
   audience would still want to hear is not an outlier.
3. Rate COHERENCE 1-5:
   5 = every talk clearly belongs; a crisp session an attendee would happily sit through
   4 = clear theme; one or two talks somewhat peripheral
   3 = recognizable theme, but several peripheral talks or two loosely joined sub-themes
   2 = loose grab-bag with only a weak common thread
   1 = no coherent theme
Judge each session independently, against the same standard.

## Output
Write `/home/claude/sessbuild/judge/batch_{K}.out.json`: a JSON array, one object per session in
file order: {"session": "X012", "theme": "...", "coherence": n, "outliers": ["id", ...],
"comment": "<= 25 words"}. Check with python that it is valid JSON with {N} entries.
Finish with one line giving the mean coherence of the batch.
