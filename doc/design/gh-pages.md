
# Stage G1: GitHub Pages publishing

Extend the local Jekyll report generator described in `doc/design/report.md`
with explicit, user-initiated GitHub Pages publishing. Keep local generation
independent of credentials and network access.

## Confirmed decisions

- The repository is always named `starbash-public`.
- It must be public and owned by the authenticated user.
- Replace the current top-level `sb publish` behavior with the explicit
    `sb publish github rewrite` command; do not retain `sb publish` as an alias.
- `sb publish github --login` runs Device Authorization Flow and saves or
    replaces the OAuth credential before continuing with publication.
- `sb publish github` regenerates and uploads the site. It creates the
    repository and configures Pages when necessary.
- Deploy only the `gh-pages` branch at the repository root. Ignore all other
    branches.
- Every upload replaces `gh-pages` with a fresh orphan commit. Existing
    `gh-pages` contents are replaced automatically.
- Conflicting Pages configuration is overwritten.
- Upload waits for the Pages deployment to complete.
- Keep the generated local site at
    `~/.local/state/starbash/publish/site` after upload.
- `sb publish github --dry-run` performs local generation and validation, shows the files
    and planned API operations, and makes no GitHub mutations.
- Print the verification URL and attempt to open it, warning that manual
    opening may be required.
- Running `publish github --login` is the reauthentication mechanism.
- Use an informative commit message containing the publication date/time.
- Webhooks are not needed.

## Commands and behavior

### `sb publish github rewrite`

Regenerate the local Jekyll site without authentication or network access. Keep
the existing local preview workflow usable through `just site-view`. Validation
must use an explicit temporary Jekyll destination and must never create a
project-root `_site` directory.

### `sb publish github [--dry-run] [--login]`

Load the saved credential, or run Device Authorization Flow when `--login` is
specified or no credential is available. Regenerate the local site and, unless
`--dry-run` is specified, publish only the generated site files to the
authenticated user's public `starbash-public` repository. Create the repository
if absent. Configure Pages for `gh-pages` at `/`, overwriting conflicting
configuration. Wait for deployment completion and report the repository URL,
Pages URL, commit, and final status.

## Authentication plan

Use the Device Authorization Flow rather than a localhost callback server:

1. request a device code;
2. print the verification URL and user code with Rich markup;
3. ask the user to press Return before attempting to open the URL, because the
    browser may open in front of the CLI;
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

`sb publish github --dry-run` must regenerate the local site, validate
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

# Stage G2: Simplify the GitHub publishing command

Replace the two-step `init`/`upload` interface with one user-facing command:

```text
sb publish github [--dry-run] [--login]
```

## Plan

1. Remove the public `sb publish github init` and
     `sb publish github upload` commands. Keep the credential and publishing
     service boundaries from Stage G1; only the Typer interface and orchestration
     flow change.
2. Add the `github` command options:
     - `--login` always runs Device Authorization Flow, replacing the saved
         credential before continuing with the requested publication.
     - Without `--login`, load the saved credential when available.
     - If no credential is available, automatically run Device Authorization
         Flow and continue after successful authentication.
     - `--dry-run` performs the existing local generation and validation plan,
         without mutating GitHub. A missing credential still triggers login unless
         the command can complete the dry run without authentication; document and
         test the chosen behavior explicitly.
3. Make the command orchestration explicit and ordered:
     authentication (when required), local site generation and validation, then
     either a dry-run report or the GitHub publication workflow. Do not run the
     publication steps after a cancelled, expired, or failed login.
4. Preserve the existing output guarantees: never expose token contents,
     clearly distinguish local work from GitHub mutations, print the repository,
     commit, Pages URL, and deployment status, and report actionable recovery
     instructions when authentication or publication fails.
5. Update CLI help, user documentation, examples, and `justfile` recipes to
     use only the consolidated command. Remove references to the old subcommands.
6. Add or update tests for credential reuse, implicit login, forced login,
     dry-run non-mutation, cancelled/failed Device Flow, and successful
     publication. Assert resulting behavior and API calls rather than only
     checking that mocks were invoked.

## Acceptance criteria

- `sb publish github` reuses a valid saved credential and publishes once.
- `sb publish github --login` reauthenticates before publishing.
- `sb publish github` with no saved credential performs the login flow
    automatically.
- `sb publish github --dry-run` generates and validates locally and performs no
    mutating GitHub operation.
- The old `init` and `upload` command paths are no longer advertised or
    accepted.
- Local `rewrite` behavior and the generated-site retention requirement from
    Stage G1 remain unchanged.

# stage g3 make fb show the hero as a thumbnail

notes from a different ai to get you started
Since you are using Jekyll, you can automate this by adding liquid variables to your layout template.
## How to Configure Jekyll for Facebook Thumbnails

* Locate the Head Layout: Open your head template file, which is usually found in _includes/head.html.
* Insert Dynamic Meta Tags: Paste these Open Graph tags inside the <head> section:

<meta property="og:title" content="{{ page.title | default: site.title }}" />
<meta property="og:description" content="{{ page.description | default: site.description | strip_html | strip_newlines | truncate: 160 }}" />
<meta property="og:url" content="{{ page.url | absolute_url }}" />
{% if page.image %}
  <meta property="og:image" content="{{ page.image | absolute_url }}" />
{% elsif site.default_image %}
  <meta property="og:image" content="{{ site.default_image | absolute_url }}" />
{% endif %}

* Configure site.url: Ensure your base URL is defined in _config.yml so absolute_url works properly:

url: "https://github.io"baseurl: "/your-repo-name" # Leave blank "" if using a custom root domaindefault_image: "/assets/images/default-share.jpg"

* Set Image in Front Matter: For specific blog posts or pages, define the custom thumbnail at the top of the markdown file:

---layout: post
title: "My Awesome Post"image: "/assets/images/my-post-thumbnail.jpg"
---

* Scrape the Live URL: Push your changes to GitHub, wait for the build to finish, and paste the live link into the [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/) to refresh the cache.

If you'd like, let me know:

* Are you using a pre-made theme (like Minima) or a custom layout?
* Do you want to try the jekyll-seo-tag plugin to handle this automatically?

The jekyll-seo-tag plugin is an official, officially supported Jekyll plugin that automatically adds Facebook Open Graph tags, Twitter Cards, and Google search metadata to your site without making you write manual HTML templates.
## Why Use jekyll-seo-tag?

* No Manual HTML: It generates perfect meta tags automatically.
* Facebook & Twitter Ready: It handles og:image, og:title, and structural layout out of the box.
* Valid Absolute URLs: It automatically uses your _config.yml setup to build valid image links.

## How to Install It

* Add to Gemfile: Open your Gemfile and insert the plugin name:

gem "jekyll-seo-tag"

* Add to Config: Open your _config.yml and register the plugin under the plugins list:

plugins:
  - jekyll-seo-tag

* Insert Tag in Layout: Open your head template file (usually _includes/head.html) and replace any existing title or meta tags with this single line:

{% seo %}


## How to Define Your Thumbnails

* Set Global Default: In your _config.yml, add a global site title, description, and fallback share image:

title: "My GitHub Pages Site"description: "A cool blog built with Jekyll."url: "https://github.io"baseurl: "/your-repo-name"image: "/assets/images/global-share.jpg"

* Set Page-Specific Thumbnails: For any specific blog post or page, add the image path directly to its Front Matter:

---layout: post
title: "New Feature Launch"image: "/assets/images/feature-thumbnail.jpg"
---


Once you push these changes to GitHub, you will still need to run your live URL through the [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/) one last time to clear old cached previews.
If you want, tell me:

* Are you hosting on GitHub Pages standard environment, or using GitHub Actions to build your Jekyll site?
* Do you need help formatting Twitter-specific card options within the plugin?
