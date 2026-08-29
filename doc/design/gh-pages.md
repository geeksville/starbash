
# Stage G1: GitHub Pages publishing

Extend the local Jekyll report generator described in `doc/design/report.md`
with explicit, user-initiated GitHub Pages publishing. Keep local generation
independent of credentials and network access.

## Confirmed decisions

- The repository is always named `starbash-public`.
- It must be public and owned by the authenticated user.
- Replace the current top-level `sb publish` behavior with the explicit
    `sb publish github rewrite` command; do not retain `sb publish` as an alias.
- `sb publish github init` only runs Device Authorization Flow and saves or
    replaces the OAuth credential. It does not create repositories or upload.
- `sb publish github upload` regenerates and uploads the site. It creates the
    repository and configures Pages when necessary.
- Deploy only the `gh-pages` branch at the repository root. Ignore all other
    branches.
- Every upload replaces `gh-pages` with a fresh orphan commit. Existing
    `gh-pages` contents are replaced automatically.
- Conflicting Pages configuration is overwritten.
- Upload waits for the Pages deployment to complete.
- Keep the generated local site at
    `~/.local/state/starbash/publish/site` after upload.
- `upload --dry-run` performs local generation and validation, shows the files
    and planned API operations, and makes no GitHub mutations.
- Print the verification URL and attempt to open it, warning that manual
    opening may be required.
- Running `publish github init` is the reauthentication mechanism.
- Use an informative commit message containing the publication date/time.
- Webhooks are not needed.

## Commands and behavior

### `sb publish github rewrite`

Regenerate the local Jekyll site without authentication or network access. Keep
the existing local preview workflow usable through `just site-view`. Validation
must use an explicit temporary Jekyll destination and must never create a
project-root `_site` directory.

### `sb publish github init`

Run GitHub's Device Authorization Flow using the registered Starbash OAuth
application, then securely save the resulting credential. Explicit invocation
always permits reauthentication. Report authentication failures without
exposing token contents.

### `sb publish github upload [--dry-run]`

Load the saved credential, regenerate the local site, and publish only the
generated site files to the authenticated user's public `starbash-public`
repository. Create the repository if absent. Configure Pages for `gh-pages` at
`/`, overwriting conflicting configuration. Wait for deployment completion and
report the repository URL, Pages URL, commit, and final status.

## Authentication plan

Use the Device Authorization Flow rather than a localhost callback server:

1. request a device code;
2. print the verification URL and user code with Rich markup;
3. attempt to open the URL with the platform browser mechanism;
4. warn that the printed URL may need to be opened manually; and
5. poll using GitHub's requested interval until success or a terminal error.

Handle authorization pending, slow-down, expiration, denial, malformed
responses, network errors, rate limits, and unexpected errors. Use the client
ID from the registered Starbash OAuth application and keep it explicit and
configurable.

Use the narrowest GitHub permissions that support this exact workflow. The
workflow needs authenticated-user lookup, creation of one public user-owned
repository, repository content/ref updates, and Pages administration. Confirm
whether the current GitHub OAuth application should request classic `repo`
scope, or whether narrower repository-content and Pages permissions are
available. Do not request organization access.

Prefer a maintained cross-platform Python credential manager that supports
secure non-interactive CLI use. If no suitable dependency is available, store a
credential file such as `github-auth.toml` under the platform-specific
Starbash config directory with restrictive permissions. Never include tokens in
logs, reports, generated site files, API error text, tests, or telemetry.

## GitHub API and deployment design

Add a small mockable GitHub service boundary. Keep Typer commands independent
of PyGithub and raw HTTP details. PyGithub is preferred if it supports all
required repository, tree/blob/commit/ref, and Pages operations; otherwise use
raw HTTP behind the same boundary.

The upload sequence is:

1. regenerate the local site;
2. enumerate only generated files under the configured site directory;
3. exclude credentials, `.git`, temporary files, unrelated files, and any
     project-root `_site` directory;
4. create blobs and a tree containing only those files;
5. create a parentless commit with a message such as
     `Publish Starbash images (YYYY-MM-DD HH:MM UTC)`;
6. create or force-update the `gh-pages` ref;
7. configure Pages for `gh-pages` and `/`, overwriting conflicts; and
8. wait for the Pages deployment/build result.

Only `gh-pages` may be changed. Use staged API operations so a failed tree or
commit does not partially replace the live branch. Do not claim success until
the ref update and Pages deployment both succeed.

## Dry-run behavior

`sb publish github upload --dry-run` must regenerate the local site, validate
it with Jekyll into an explicit temporary destination, list files and sizes,
show the target repository, branch, commit message, and Pages configuration,
and make no mutating GitHub calls. Loading a saved credential for a read-only
identity check is allowed, but the output must state what was not changed.

## Error handling and recovery

Provide concise actionable errors for missing or revoked credentials, cancelled
or expired Device Flow, insufficient permissions, network/rate-limit failures,
repository conflicts, tree/commit/ref failures, Pages conflicts, deployment
failures, and local generation/Jekyll failures. If repository creation succeeds
but a later step fails, report that fact and explain how to retry safely.

## Implementation phases

1. Add the `publish github` command group, move local generation to `rewrite`,
     and define credential, GitHub service, deployment, and Pages models.
2. Implement Device Flow, secure credential persistence, browser opening,
     fallback messaging, and mocked polling/error tests.
3. Implement authenticated-user lookup and exact `starbash-public` discovery or
     creation, with repository and permission tests.
4. Implement generated-file enumeration, orphan tree/blob/commit creation, and
     automatic `gh-pages` replacement while ignoring other branches.
5. Implement idempotent/overwriting Pages configuration, deployment polling,
     status reporting, and `upload --dry-run`.
6. Validate with explicit temporary Jekyll destinations, test repeat uploads,
     document permissions and recovery, and preserve the local generated site.

## Remaining question

Confirm the least-privilege GitHub OAuth scope/permission set for public
repository creation, contents/ref updates, and Pages administration. The
provided sample uses the classic `repo` scope as a working fallback.

## Webhooks

Webhooks are out of scope. Publishing is explicitly user initiated.



## pushing to github pages

You want **PyGithub**. It’s the defacto standard for wrangling the GitHub REST API in Python. If you want to be a hipster about it, you can use **ghapi**, which dynamically generates itself from GitHub's OpenAPI spec so it never misses an endpoint.

Assuming your app already OAuth'd the user and got a token with `repo` scope, here is the PyGithub speedrun to spin up a Jekyll site:

```python
from github import Github, Auth

# Authenticate as your user
auth = Auth.Token("USER_OAUTH_TOKEN")
g = Github(auth=auth)
user = g.get_user()

# 1. Create the repository
repo = user.create_repo("my-sweet-blog", auto_init=True)

# 2. Dump in the Jekyll bare minimums
repo.create_file(
    path="_config.yml", 
    message="init config", 
    content="theme: jekyll-theme-hacker\ntitle: My Blog"
)
repo.create_file(
    path="index.md", 
    message="init index", 
    content="# Hello World\n\nThis actually worked."
)

# 3. Turn on GitHub Pages
# If your PyGithub version is lagging and lacks repo.create_pages_site():
repo._requester.requestJsonAndCheck(
    "POST", 
    f"{repo.url}/pages", 
    input={"source": {"branch": "main", "path": "/"}}
)

```

Just remember to handle the exceptions for when your users inevitably try to name their repository something illegal or run out of free actions minutes.

## oauth sign in

PyGithub won't hold your hand for the initial OAuth handshake—it expects you to show up with a valid token already in your pocket.

For a CLI app, you absolutely don't want to mess with spinning up localhost web servers to catch redirect callbacks. You want GitHub's **Device Authorization Flow**. It’s exactly what the official `gh` CLI uses.

You just ask GitHub for a code, tell the user to type that code into their browser, and then stubbornly poll GitHub's API until the user actually does it.

Here is the exact code to do it, using `requests` and `rich` (because you should be using `rich` for CLI output anyway):

```python
import requests
import time
from rich.console import Console

console = Console()
CLIENT_ID = "Iv23liewanBO4WT8No6v"

# 1. Ask GitHub for a device code
response = requests.post(
    "https://github.com/login/device/code",
    headers={"Accept": "application/json"},
    data={"client_id": CLIENT_ID, "scope": "repo"}
).json()

device_code = response["device_code"]
user_code = response["user_code"]
verification_uri = response["verification_uri"]
interval = response["interval"]

# 2. Yell at the user to go to the browser
console.print(f"[bold yellow]1. Open:[/bold yellow] [link={verification_uri}]{verification_uri}[/link]")
console.print(f"[bold yellow]2. Enter this code:[/bold yellow] [bold green]{user_code}[/bold green]")

# 3. Aggressively poll GitHub until the user complies
with console.status("[bold cyan]Waiting for you to authorize in the browser...[/bold cyan]"):
    while True:
        token_response = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }
        ).json()

        if "access_token" in token_response:
            access_token = token_response["access_token"]
            console.print("[bold green]Success! We got the token.[/bold green] :rocket:")
            break
        elif token_response.get("error") == "authorization_pending":
            time.sleep(interval)
        else:
            console.print(f"[bold red]Something went wrong:[/bold red] {token_response}")
            break

# 4. Now hand it off to PyGithub
# from github import Github, Auth
# g = Github(auth=Auth.Token(access_token))

```

Just remember to go into your GitHub OAuth App settings and explicitly enable the **Device Flow** checkbox, or GitHub will just laugh at your initial POST request.

## reuploading

Because Git is essentially a digital hoarder, it will absolutely keep every single version of your JPEGs in the `.git` directory forever unless you explicitly sever the timeline.

To push to GitHub Pages without the bloat, you need to abuse the "orphan" branch feature. This creates a completely disconnected branch with zero parents, meaning it carries exactly zero historical baggage.

**The Manual CLI Way:**
Run this whenever you want to update your images and obliterate the past:

```bash
# Create a brand new branch with amnesia
git checkout --orphan temp-pages

# Add your updated images and make the one and only commit
git add .
git commit -m "Fresh images, zero history"

# Brutally murder the old local branch and take its name
git branch -D gh-pages
git branch -M gh-pages

# Force push to GitHub to overwrite their reality
git push -f origin gh-pages

```
