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
