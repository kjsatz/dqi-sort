# dqi-sort

Tools for sorting the Division of Quantum Information (DQI) abstracts for the APS Global Physics Summit into sessions, scheduling those sessions into rooms, and recruiting session chairs. Claude drafts each step; people decide at fixed checkpoints.

**Start with [PROCESS.md](PROCESS.md).** It describes the whole process: the stages, who decides what, the review sheets, scheduling and chairs. This is the part we most want opinions on.

## Status

The process is designed and was tested on the 2026 superconducting sessions (see [prototype/README.md](prototype/README.md)). We are now doing a dry run on the full 2026 abstracts, before the 2027 abstracts arrive in November. So far the parser for the APS export and the embedding tools are written; the rest of the pipeline is being built.

## Giving feedback on the process

Comment on the open PROCESS.md review pull request: click the `+` next to any line to leave a comment there, or add a general comment on the pull request. Questions, objections and "this won't work because..." are all welcome.

## Contributing

- **No conference data in this repo.** It is public. Abstracts, names, emails, sorts and schedules live in a separate private data repo, one per year. Every command takes that data folder as an argument. Test data must be made up.
- `main` is protected: make a branch and open a pull request. A check refuses data files and runs the tests.
- Turn on the same data check locally before your first commit:

  ```
  git config core.hooksPath .githooks
  ```

- Set up and test:

  ```
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  .venv/bin/python -m pytest tests
  ```

## Layout

- `PROCESS.md`: the process, data format and rules.
- `dqi_sort/`: the pipeline (`intake.py` reads the APS export; `embed.py` and `score_embeddings.py` handle embeddings).
- `prompts/`: prompts for Claude, such as the presentation-card spec.
- `docs/`: how-to notes, e.g. [docs/embeddings.md](docs/embeddings.md).
- `prototype/`: scripts and prompts from the first test; reference only.
- `CLAUDE.md`: working instructions for Claude Code, which builds and runs most of this.

## License

MIT; see [LICENSE](LICENSE).
