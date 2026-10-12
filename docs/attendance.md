# Attendance model

Estimates how many people a proposed session will draw, so popular sessions get rooms that fit them. Code: `dqi_sort/attendance.py`.

## Data

`DATA_DIR/history/attendance.csv`: one row per past session, from the APS RFID badge data (badges are tracked in and out of each room) and the APS room grids. The header lists the source spreadsheets. The target is **peak**, the most people inside at once: it is what a room must seat. A session whose peak reached 90% of its room's capacity counts as **full**, so its peak is only a lower bound on demand.

## Model

```
log(peak) = interest + slot effect + year effect + noise
interest  = session-type effect + title term
```

- **Interest** is what a session would draw in an average slot. The title term averages the 10 most similar past sessions, by EmbeddingGemma embedding of `"<type> session: <title>"`, after removing their own slot and year effects. Session titles only: talk lists and speakers would add a little, but much of what makes a topic popular in a given year is not in the data either way.
- **Slot effect**: day (Monday to Friday) and time of day (morning, midday, afternoon). It is used only to size a room once a session has its slot, never to decide which sessions get which slots (see Scheduling in `PROCESS.md`).
- **Full rooms** are censored: the fit only requires their demand to be at least the observed peak.
- Type, slot and year effects are shrunk toward "no effect" (worth 10 sessions of evidence), because with two years of data they are partly confounded with past scheduling choices: if weaker sessions tended to land on Friday, some of that shows up as a Friday effect.
- A new year's overall level is unknown; predictions use the average of the past years.

## Commands

```
python -m dqi_sort.attendance fit DATA_DIR        # writes DATA_DIR/history/attendance_model.npz
python -m dqi_sort.attendance check DATA_DIR      # fit on the earliest year, predict the latest
python -m dqi_sort.attendance predict DATA_DIR --title "Superconducting Qubit Readout" --type contributed [--day Fri --start 08:00]
python -m dqi_sort.attendance predict DATA_DIR --sessions DATA_DIR/sorting/sessions.csv
```

`python -m dqi_sort.attendance_report DATA_DIR` refits the model and writes `DATA_DIR/history/attendance_report.md` with three figures (fit on the training data; predicted vs actual on the held-out year; type, day and time effects with ranges). Notable sessions can be named on the plots in `DATA_DIR/history/attendance_labels.csv` (year, session_code, label) and the past sessions that drew the most and least. Rerun it after adding a year.

With `room_sizes` (and `symposium_min_seats`) in `config.yaml`, `predict` also suggests a room size class: the smallest whose room at 90% full holds the expected attendance, symposia at least the minimum, with "may overflow" when the high end of the range exceeds the room. People keep or override it at sort review, then a budget round fits the totals to the rooms available (see Scheduling in `PROCESS.md`).

`predict` prints each session's interest with a 68% range and the past sessions it resembles, plus the expected peak in a given slot. Fitting and predicting need Ollama running with `embeddinggemma` (see `docs/embeddings.md`). In Python: `load(DATA_DIR)` returns a model with `interest(...)`, `slot_factor(day, start)` and `in_slot(...)`.

## How good it is

Fitted on 2025 alone and asked to predict 2026 (175 sessions), Oct 2026:

- R² 0.27 on the plotted (linear) scale; on its own training data (both years) R² is 0.35
- typical error a factor of 1.36; within a factor of 1.5 for 62% of sessions
- rank correlation with actual peaks 0.61 (session type alone: 0.31)
- of the 45 sessions that drew 130 or more, it flagged 16, with 14 false alarms

So it ranks sessions well and is useful for deciding which sessions should get the larger rooms, but it misses many individual crowds. Treat it as one input next to the reviewers' judgment, and use the upper end of the range when a full room would be costly.

Known limits: two years of data (about 310 sessions); the time-of-day blocks are coarse.
