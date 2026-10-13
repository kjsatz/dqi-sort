You are doing stage 3 (linking) of sorting the APS Division of Quantum Information (DQI) abstracts into sessions:
multi-part series, pair requests, and institutions. Data is private: write only the files named below.

## Input (in `{DATA}/work/linking/`)

- `series_candidates.md`: talks that may be one part of a series (card hints, "Part ..." titles, shared abstracts),
  grouped into proposed series.
- `pair_requests.md`: talks whose submitter asks to follow, precede or share a session with another talk.
- `affiliations_new.txt`: submitted affiliations not yet mapped to an institution, with their number of talks.

To look up talks by speaker or title, search `{DATA}/talks.csv` (columns talk_id, track, type, title, speaker,
affiliation, series, status, ...; active talks only) with grep or a short script. Read nothing else. Keep helper
scripts in `{DATA}/work/linking/scratch/`.

## 1. Series and pairs: write `{DATA}/linking/series.csv`

Columns: series_id, talk_id, part, sure, note. IDs S001, S002, ...; parts 1, 2, ... in presentation order.

- A series is two or more talks that the submitters say belong together as parts (Part I/II, theory/experiment
  pairs, a shared abstract split across talks). Match by title, speaker and the card's partner hints, not by category.
- A pair request becomes a two-part series in the order asked, with note "pair request: ...", when the submitter asks
  to follow, precede, be back to back with, or share a session with ONE specific talk in talks.csv. Skip requests
  about days or times only, requests naming a talk or person not in talks.csv, vague group requests, and requests to
  be apart. If the request is only "same session", put the requester second and note "order not requested".
- If a pair partner is already in a series, add the requester as the next (or previous) part of that series.
- `sure` = yes when the link is clear; no when you matched with doubt (say why in note). Unsure links go to the lead.

Requests to be AWAY from a specific talk (not in the same session) go to `{DATA}/linking/apart.csv` instead, with
columns talk_a, talk_b, note (one row per pair, both talks in talks.csv). The session checks refuse a session holding
both.

## 2. Institutions: add rows to `{DATA}/institutions.csv`

It already maps the affiliations seen before (affiliation, institution). Add one row for every affiliation in
`affiliations_new.txt`, mapping it to a short canonical institution name, consistent with the names already in the
file (e.g. "MIT" and "Massachusetts Institute of Technology" -> "Massachusetts Institute of Technology"). Separate
sites stay separate (NIST Boulder and NIST Gaithersburg; JILA; MIT Lincoln Laboratory is not MIT). A company and
its research lab are one institution. Keep the affiliation text exactly as listed.

## 3. Apply

Run `cd {CODE} && .venv/bin/python -m dqi_sort.linking apply {DATA}` and fix every error it reports until it
succeeds. Finish with a short summary: series (sure / unsure), pairs, institutions added, and anything for the lead.
