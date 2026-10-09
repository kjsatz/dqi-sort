# Prototype (2026 superconducting test)

Scripts and prompts from the first test on the 2026 superconducting sheet (567 talks). They have hard-coded paths and are kept as reference while the real pipeline is built in `dqi_sort/`. Results live in the private data repo under `reference/2026_superconducting_test/`. Values taken from the data (session families, manual talk links) are read from `prototype_constants.json` in that folder, not kept here.

What each piece did:

- `scripts/parse.py`, `scripts/prep.py`: parse the APS sheet export; resolve multi-part talks; render compact talk cards.
- `prompts/bucket_prompt.md`: Opus builds sessions from one category bucket (step-3 test).
- `prompts/plan_prompt.md`: Opus reads all cards and writes a 43-session plan (and in practice a full draft assignment).
- `prompts/assign_prompt.md`: fresh Opus agents score each talk against the plan (fit 3/2/1, top 3).
- `scripts/solve.py`: OR-Tools CP-SAT assignment under capacity, linked talks together.
- `prompts/review_prompt.md`: Opus reviews one family of sessions, makes local moves, orders talks.
- `prompts/judge_prompt.md`: blind Opus judge rates session coherence 1-5 with outliers.
- `scripts/validate.py`, `scripts/validate_plan.py`: checks used by the agents.
- `scripts/partcmp.py`, `scripts/compare.py`: pair agreement / ARI between sorts.
- `scripts/experiment.py`, `scripts/lda_test.py`, `scripts/mapdata*.py`, `scripts/map_template.html`: embedding comparison and the interactive map.

Key results: the planner's plan is the real decision (fresh assigners reproduced it 98%); two independent plans agreed on 48% of talk pairs; each agreed with the human sort on 29-34%; blind judge mean coherence 4.16 (Claude) vs 3.86 (human); embeddings (bge-small) reach ARI 0.22 vs human, below Claude's plan at 0.32.
