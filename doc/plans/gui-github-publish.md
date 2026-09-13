# GUI: publish to GitHub (setup dialog + shared publish sequence)

Goal: make the GUI's **Publish** page able to actually publish, not just generate
the local site.  A first-time GUI user has no OAuth token and has not installed
the Starbash GitHub App, so the page has to walk them through both — the same
two steps the CLI prompts for — and then carry on publishing without them
having to press the button again.

## Why

`sb publish github` already worked end to end, but all of its logic lived inside
`src/starbash/commands/publish.py` in a Rich/prompt-shaped function
(`_publish_github`, with `_authenticate`, `_require_app_installation`,
`_upload_blobs`).  The GUI could not reuse any of it, and duplicating it would
have meant two implementations of a sequence with real consequences (repository
creation, commits, credential storage) drifting apart.  So the sequence was
extracted first, then both front ends were wired to it.

## Approach

### 1. Core: `src/starbash/publish/github_publish.py` (new, front-end-agnostic)

The whole "sign in → check App → create repo → upload blobs → commit → configure
Pages" sequence, with **no** Rich, terminal or Qt imports.  Callers supply a
`StepReporter` (`Callable[[str, int, int], None]`, i.e. `(description, completed,
total)`) and do their own user-facing work.

Contents: `CLIENT_ID`, `APP_SLUG`, `APP_INSTALLATION_URL`, `PUBLISH_REPOSITORY`
(`"starbash-public"`), `UPLOAD_PATH_BLACKLIST` (`("Gemfile", "github-auth.toml")`
— the local Jekyll bundle, and a stray credential file), `MAX_BLOB_UPLOADS = 4`,
the frozen `PublishResult(owner, pages_url, file_count)`,
`GitHubAppNotInstalledError`, and `pages_url_for`, `credential_service`,
`refresh_if_needed`, `save_credential`, `finish_device_login`, `collect_site_files`,
`upload_blobs`, `publish_site`.

Deliberate choices:

- `publish_site(..., require_app: bool = True)` — `starbash-public` must be
  *public* for Pages to serve it, and the App check is the only place that knows
  the difference between "no credential" and "credential but no installation".
  A front end that has already guided the user past installation passes
  `require_app=False` (the GUI does, since it checks right before calling).
- `finish_device_login(..., sleeper=...)` takes a sleep function so a front end
  with a cancel button can interrupt GitHub's multi-second poll interval.
- `GitHubCredential` carries a persisted `login` — the account the token belongs
  to.  GitHub's token response has no such field, so it is filled in by whoever
  asks GitHub who the user is (`github_install_job`, `publish_github_job`);
  `credential_service`'s rotate callback and `refresh_if_needed`'s return value
  both **carry it across a token refresh**, since a routine refresh must not erase
  the name.  Credentials written before the field existed simply load with
  `login == ""`.
- `refresh_if_needed` **returns** the credential now in effect (rotated or not)
  rather than `None`, so a caller that wants to save something beside the token
  cannot accidentally write back the expired one it passed in.

### 2. CLI: `commands/publish.py` reduced to prompts + rendering

`_publish_github` now keeps only what is genuinely CLI-specific: the Rich panels,
the interactive prompts (`_authenticate` / `_require_app_installation`, which open
GitHub's pages with `webbrowser`), and the rendering — the step callback drives a
Rich `Progress` (spinner + bar + `completed/total`) and ignores nothing else.
`_upload_blobs` and the rest of the sequence are gone from the command.  Its
behaviour is unchanged (`tests/unit/test_publish_commands.py` still covers the
command, with the blob-concurrency test relocated to the new core test module).

### 3. GUI jobs: `ui/qt/jobs.py`

Three new worker-thread jobs (each builds its own `Starbash`, per the GUI
threading rule) plus one cancellation helper:

- `github_sign_in_job(report, token)` — device flow.  Reports
  `{"user_code", "verification_uri"}` as soon as GitHub issues the code (so the
  dialog can display and open it while the thread keeps polling), and returns
  `{"credential": <raw token dict>}`.  The credential is **deliberately not
  saved**: the caller installs the App first and only then persists it, so a
  half-finished sign-in never leaves a credential that cannot publish.
- `github_install_job(report, token, credential=None)` — loads the stored
  credential (here, off the GUI thread — the keyring is not the GUI's to touch),
  checks `app_is_installed`, and only on success calls `save_credential` — saving
  the credential **with the account name GitHub reports** so the Publish page can
  show who is signed in without asking again.
  Returns `{"signed_in", "installed", "login"}`; `signed_in=False` is how the
  dialog learns the stored credential is gone and it must start over.
- `github_identity_job(report, token)` — what the Publish page shows: loads the
  stored credential off the GUI thread and returns `{"signed_in", "login"}`.
  `login` comes from the credential itself, so it makes no network calls; it is
  empty for a credential saved before Starbash recorded account names.
- `publish_github_job(report, token)` — the full publish, for the account GitHub
  reports for the stored credential (so there is no username to pass in).  It
  records that account beside the token too, which is how an upgraded install
  learns the name.  Reports each `publish_site` step as a
  `(description, completed, total)` tuple, which is what drives the page's
  progress bar.
- `_cancel_aware_sleeper(token)` — slices the device-flow sleep into 0.1s
  chunks and checks `token.raise_if_cancelled()`, so a closed dialog's worker
  stops promptly instead of living for another poll interval.

**Key decision — `needs_sign_in` / `needs_install` are returned, not raised.**
Both are normal steps for a new user, not errors, and the job can be re-run
verbatim afterwards:

```python
{"needs_sign_in": True, "message": "Sign in to GitHub to publish the site."}
{"needs_install": True, "message": "The Starbash GitHub App is not installed ..."}
```

An error dialog for either would be exactly the wrong tone, and a re-run needs no
state passed back in — the credential is read fresh from the store on the next
attempt.

### 4. GUI dialog: `ui/qt/widgets/github_login.py` (new)

`GitHubSetupDialog(QDialog)` — one widget set reused across four steps
(`STEP_WELCOME` → `STEP_WAITING` → `STEP_INSTALL` → `STEP_DONE`), driven by
`_show_step(step)`; `_on_primary` / `_on_secondary` dispatch by step.  The narrow
contract with the caller: the dialog either ends with the App installed and the
credential stored (`dialog.ready is True`), or it does not.
`run_github_setup(parent, *, start_at_install=False) -> bool` is the module-level
entry point the page uses.

- `start_at_install=True` (a token exists but the App does not) opens the
  installation page and checks immediately, instead of asking the user to sign in
  again.
- A device-flow failure before a code was issued returns to `STEP_WELCOME`; a
  failure after returns to the same step with the button re-enabled, always with
  `"…  You can try again."` appended.
- Closing the window (`closeEvent`) is treated exactly like **Cancel** (`reject`):
  both call `_stop_worker()`, which cancels the in-flight token and sets
  `_closed`, and every callback starts with `if self._closed: return` — so a late
  result cannot touch a dead window.
- `theme.py` gains a `DeviceCode` rule: the device code is the one thing the user
  must read accurately, so it is rendered large and monospaced.
- The dialog is shown once (on `STEP_WELCOME`), so a later step that *reveals*
  text must re-fit the window: `_show_step` ends in `_refit()`, and every
  `_status` update goes through `_set_status()`, which sets the text then
  re-fits.  `_refit()` clears the wrapped labels' minimum heights, activates the
  layout, re-measures with `heightForWidth()` at the real width, activates again
  and `adjustSize()`s.  Skipping the minimum-clearing step is the trap: `QLabel`
  clamps its hints by the minimum it was last given, so the window would grow and
  never shrink; `adjustSize()` alone left word-wrapped text clipped because
  `sizeHint()` under-reports height at that width.  Covered by
  `test_a_revealed_step_is_not_clipped`.

### 5. GUI page: `ui/qt/pages/publish.py`

"Publish to GitHub" (styled `#Primary`) sits beside *Open in browser*, next to a
compact `Spinner`, with a `QProgressBar` below them that is hidden unless a publish
is in flight.

- **The account field is read-only.**  It shows the account GitHub has Starbash
  signed in as (`refresh()` runs `github_identity_job`, which reads the name recorded
  with the credential); the user never types it.  Publishing therefore uses the
  account GitHub reports — there is no username for the page to pass in.
- **"Open in browser" starts disabled** and is enabled only once a publish has
  reported a `pages_url`, which is the `https://<owner>.github.io/starbash-public/`
  Pages site.  A later *failed* publish keeps the link to the site that is already
  up.  (The old *Generate report site* and *Open site folder* buttons are gone:
  generating without publishing was a dead end, and the site directory is still
  shown in the status line.)

`_on_publish` locks the buttons, starts the spinner, and shows an indeterminate bar.
On completion, `_on_published` either finishes (`_finish_publish(message)`, which
emits the page's `status` signal for the window's status bar) or opens the setup
dialog and, when it succeeds, simply calls `_on_publish()` again.  A cancelled
dialog leaves "Publishing cancelled."  Progress payloads are rendered as a bar
when they are a `(description, completed, total)` tuple and as text otherwise.

## Files

| File | Change |
| --- | --- |
| `src/starbash/publish/github_publish.py` | **new** — the shared sequence |
| `src/starbash/publish/credentials.py` | credential gains a persisted `login` |
| `src/starbash/commands/publish.py` | reduced to prompts + Rich rendering |
| `src/starbash/ui/qt/jobs.py` | 4 new jobs + `_cancel_aware_sleeper` |
| `src/starbash/ui/qt/widgets/github_login.py` | **new** — setup dialog |
| `src/starbash/ui/qt/widgets/__init__.py` | export the dialog |
| `src/starbash/ui/qt/pages/publish.py` | Publish button, bar, setup handoff |
| `src/starbash/ui/qt/theme.py` | `DeviceCode` rule |
| `tests/unit/test_github_publish.py` | **new** — core sequence tests |
| `tests/unit/test_github_jobs.py` | **new** — account recording/readback |
| `tests/unit/test_github_setup_dialog.py` | **new** — step machine |
| `tests/unit/test_publish_page.py` | **new** — page + retry loop |

## Testing strategy

`run_async` is monkeypatched to a **recorder** (`_RecordedJob` + `_FakeWorker`) in
both GUI test modules, so no job body ever touches GitHub and the callbacks are
invoked directly on the GUI thread — exactly as the real signals would be.  The
recorder also captures the job callable, so a test can run it with a stub `report`
and assert what the page/dialog passed in (or, as on the Publish page, that it
passed nothing but the credential-reading job).

What the tests pin down (rather than "was called"):

- which job each step runs, and with which credential;
- every step transition, including the two "return to an earlier step" paths;
- that a closed dialog stops its worker **and** ignores a late result;
- that `needs_sign_in`/`needs_install` open the dialog at the right step and that
  a success re-runs the publish — the whole point of the feature;
- that the account field is **read-only** and shows what `github_identity_job`
  returns, and that the account name is persisted with the credential (round trip,
  TOML fallback, and the pre-`login` credential that must still load);
- that "Open in browser" is disabled until a publish reports a `pages_url`, opens
  that URL, and survives a later failure unscathed.

`test_github_jobs.py` stubs `credential_service`/`GitHubCredentialStore` and runs
the job bodies directly (no Qt thread pool), which is how the "recorded account"
behaviour is checked without a network.

`test_publish_page.py` patches `Page.show_error` (autouse, on the class) because a
regression that reaches `QMessageBox.critical` would **hang** a headless run
rather than fail it — the same trap documented for the Repositories page tests.

## Phased sequence (all landed)

1. Extract `github_publish.py`; make `commands/publish.py` use it; core tests.
2. Add the three GUI jobs.
3. Build the dialog (+ `theme.py` rule, widget export).
4. Rewrite the Publish page around the job/dialog loop.
5. GUI tests, `just lint`, full suite (1013 passed).
6. Follow-up: drop the dead-end generate/open-folder buttons, gate *Open in
   browser* on a successful publish, and make the account field a read-only
   readback of the account recorded with the credential (`login` on
   `GitHubCredential`, the new `github_identity_job`).  Full suite: 1027 passed.

## Risks / open questions

- **Two dialects, one sequence.** The CLI still asks its questions with Rich
  prompts; the GUI asks them with a dialog.  The *sequence* is shared, the
  *asking* is not — intentional (the CLI must stay usable over SSH), but it means
  a new question added to the sequence needs wiring in both places.
- **GitHub's own wording.** The install step asks the user to choose "All
  repositories"; a user who picks only some repositories gets a publish-time
  failure from GitHub.  The dialog says so, but nothing verifies it up front.
- **No way to sign out from the GUI yet.** `sb publish github --login` is the only
  re-authenticate path; the dialog only ever adds a credential.
- `GitHubCredentialStore` uses the OS keyring; a machine with no keyring backend
  surfaces as a job failure, which the page reports as "Publishing failed".  The
  same applies to the identity read that runs when the Publish page is shown, so a
  corrupt credential can greet the user with an error dialog on a page switch (rare,
  and it is a real error — publishing would fail too — but it is the one place a
  *refresh* can pop a modal, because `Page.start_job` always surfaces failures).
