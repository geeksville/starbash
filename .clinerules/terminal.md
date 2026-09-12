# Terminal safety

I cannot type into a shell that is waiting for input, so **any command line that
leaves the shell at a secondary prompt hangs forever**. The classic failure: a
composite one-liner that mixes `&&`, backgrounding (`&`) and quoted strings gets
one quote mis-escaped, and bash drops to its `dquote>` / `quote>` / `>` prompt.
The intended command never even starts — so don't "wait and retry", fix the
invocation.

Rules:

- **Keep each command a single, simple statement.** Do not chain backgrounding
  (`nohup ... &`, `& echo $!`) onto a long `&&` chain. If you need a long
  command, write it to a temp script file first (via the editor/heredoc) and run
  the script — the quoting is then fixed and there is nothing left to parse
  interactively.
- **Avoid `&`-backgrounding inside a composite line.** To run something long,
  either run it in the foreground with a bounded `timeout <seconds> <cmd>`, or
  redirect to a log and poll the log. Never background and then leave the line
  open with a trailing quote/prompt construct.
- **Prefer a heredoc for multi-line scripts**, and always terminate it correctly:
  `python - <<'EOF' ... EOF`, `bash <<'EOF' ... EOF`. A missing/extra `EOF` or a
  stray quote also yields the `dquote>`/`heredoc>` hang.
- **If a command seems to hang, verify before retrying.** Check whether the
  process actually started (`ps aux | grep -c '[p]ytest'`) and whether its log
  exists/grew. If neither happened, the shell hung on *parsing*, not work — do
  not re-run the same malformed line.
- **Double-check quoting of `!`/`$!`/`"`** before sending: history expansion and
  escaping can survive one layer and break the next. A short shell script file
  sidesteps all of it.

See also AGENTS.md → *Terminal commands (never block on a prompt)* for the
related pager/interactive-flag rules.
