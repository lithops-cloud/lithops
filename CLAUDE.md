# CLAUDE.md

Claude Code reads this file automatically. The project instructions shared by all AI coding
agents live in [AGENTS.md](AGENTS.md) and are imported here, so there is a single source of
truth:

@AGENTS.md

## Claude Code specifics

- Use the Python interpreter that has this checkout installed in editable mode
  (`pip show lithops` shows the *Editable project location*).
- Run `ruff check .` and the localhost test suite (with `--backend localhost --storage
  localhost`) before reporting a change as done.
- Long-running jobs (full test suite, Docker / runtime builds, docs builds) should run in the
  background.
- Ask before any action that uses cloud accounts, builds or pushes runtime images, or
  publishes content.
