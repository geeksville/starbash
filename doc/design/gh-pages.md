
# stage g1: github pages

extending the work done in doc/design/report.md... finally add github pages upload

* move the old "publish" cli cmd into "publish github rewrite" - a subcommand intended just for dev use (just rewrites ~/.local/state/starbash/publish/site)
* add a "publish github init" command:
  * if we don't already have a USER_OAUTH_TOKEN walk the user through the github device auth flow and save it in .config/.../github-auth.toml 
  * regenerate ~/.local/state/starbash/publish/site as needed
  * check to see if the user has a "starbash-public" repo, if not - create it
  * use the temp-pages (below) hack to rewrite the "main" branch" of the repo
  * create a github pages site based on that repo
  * use INFo logs to update user as these steps proceed

ai read the rest of this file for tips on how to do this.  convert into a plan.

## webhooks

I dont need to use webhooks but https://github.com/probot/smee.io or https://webhook.site/ are both good options.



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

**The Automated Way (GitHub Actions):**
If you are using a CI pipeline to push these updates, don't write that bash script yourself. The community standard `peaceiris/actions-gh-pages` action has a flag specifically designed to fix this repo bloat issue. Just add `force_orphan: true` to your workflow step, and it will automatically force-push a single-commit history on every single deploy.

*(Note: Force-pushing an orphan branch means anyone who actually cloned your `gh-pages` branch will get nasty Git errors the next time they try to `git pull`. But since it's just a static site deployment branch, that is entirely their problem).*