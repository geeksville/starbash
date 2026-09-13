# Collaboration

## Pause on major decisions

If I am genuinely torn about a significant decision — a large refactor, a change
to a core flow with non-obvious trade-offs (disk use, threading, ordering,
backwards compatibility), or anything where the only path forward is an
inelegant hack — **stop and ask the user** instead of picking one and barrelling
ahead.

- Prefer a short question with the concrete options and their trade-offs over a
  silent "clever" workaround. This is explicitly encouraged, not a sign of
  failure.
- Ask *before* writing the questionable code, not after — a 30-second question
  beats an invasive change that has to be unwound.
- It is fine to keep doing the safe, reversible groundwork (reads, searching,
  drafting a plan in `doc/plans/`) while waiting for the answer.
- When the decision is already clear from the rules, the code, or the user's
  instructions, just proceed — do not ask questions you can answer yourself.

Rule of thumb: **an inelegant hack is a last resort, not a shortcut.**

## Confirm `just lint` builds clean after editing code

**Whenever I finish editing code, I must run `just lint` and confirm it builds
clean** — not "ruff passed", the whole recipe:

```bash
just lint    # = format + _lint (ruff check src tests) + _typecheck (basedpyright)
```

- `just lint` **rewrites files** (`format` runs first: trailing whitespace, then
  `ruff check --fix` and `ruff format`). So run it *before* re-reading a diff or
  reporting success, and check `git status` afterwards for what it changed.
- It is **not** the same as `ruff check`. `basedpyright` (the same engine as
  Pylance in VS Code) is the part that catches real mistakes — on the live-display
  work it flagged `ConsoleOptions.update_height(None)` (its parameter is typed
  `int`; `reset_height()` is the correct API) and a `list[Tree]` passed where
  `Sequence[RenderableType]` was wanted, **while ruff and all 939 tests were
  green**.
- Order of operations: **edit → `just lint` → tests (`poetry run pytest -q`)**.
  If lint reformatted anything, re-run the tests, because the formatter touched
  the file.
- Pre-existing lint errors are still mine to deal with: fix them (or ask), rather
  than reporting "clean, apart from some pre-existing errors".
- Needs the dev deps: `poetry install --with dev` (`basedpyright`/`ruff` live
  there, not in the runtime install).

