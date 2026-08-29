"""Publish processed targets locally or to GitHub Pages."""

import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from starbash import console
from starbash.app import Starbash
from starbash.publish.credentials import GitHubCredentialStore
from starbash.publish.github import GitHubPublisher
from starbash.publish.github_service import GitHubError, GitHubService

app = typer.Typer()
github_app = typer.Typer()
app.add_typer(github_app, name="github")

CLIENT_ID = "Iv23liewanBO4WT8No6v"
UPLOAD_PATH_BLACKLIST = ("_layouts/",)


def _rewrite() -> Path:
    site: Path | None = None
    with Starbash("publish.github.rewrite") as sb:
        site = GitHubPublisher(sb).publish()
    assert site is not None
    console.print(f"Generated site: {site}")
    return site


@github_app.command()
def rewrite() -> None:
    """Regenerate the local GitHub Pages-compatible site."""
    _rewrite()


@github_app.command()
def init() -> None:
    """Authenticate with GitHub and save a publishing credential."""
    service = GitHubService()
    console.print(
        Panel(
            "[bold]GitHub account setup[/bold]\n\n"
            "Starbash needs permission to publish your processed images to your "
            "own public GitHub Pages site. GitHub provides the hosting, the "
            "website address, and the account that serves your images and any public "
            "workflows.\n\n"
            "If you do not have a GitHub account yet, create a free account at "
            "[link=https://github.com/signup]https://github.com/signup[/link]. "
            "Choose a username you are comfortable sharing publicly, verify "
            "your email address, and then return here. The 'free' GitHub plan is "
            "sufficient.",
            title="[bold cyan]Before we begin[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print(
        "[bold]What will happen next:[/bold]\n"
        "  [cyan]1.[/cyan] Starbash will ask GitHub for a one-time sign-in code.\n"
        "  [cyan]2.[/cyan] A browser page will ask you to approve the Starbash application (so it can create/post-to your GitHub Pages site).\n"
        "  [cyan]3.[/cyan] You will enter the displayed code on that page.\n"
        "  [cyan]4.[/cyan] Starbash will save the resulting credential in your "
        "operating system's credential store.\n"
        "\n[dim]Your GitHub password is never entered into Starbash and is never "
        "shared with Starbash.[/dim]"
    )
    try:
        device = service.device_code(CLIENT_ID)
        console.print()
        console.print(
            Panel(
                f"[bold]1. Open this page:[/bold]\n"
                f"   [link={device.verification_uri}]{device.verification_uri}[/link]\n\n"
                f"[bold]2. Enter this one-time code:[/bold]\n"
                f"   [bold green]{device.user_code}[/bold green]\n\n"
                "The code expires after a short time. If the browser does not "
                "open automatically, copy the link above into your browser.",
                title="[bold yellow]Authorize Starbash on GitHub[/bold yellow]",
                border_style="yellow",
            )
        )
        try:
            opened = webbrowser.open(device.verification_uri)
        except (OSError, webbrowser.Error):
            opened = False
        if opened:
            console.print(
                "[green]✓[/green] I opened the verification page. "
            )
        else:
            console.print(
                "[yellow]⚠ I could not open a browser automatically.[/yellow] "
                "Please open the printed link manually."
            )
        with console.status("[bold cyan]Waiting for GitHub authorization…[/bold cyan]"):
            token = service.poll_device_token(device, CLIENT_ID)
        GitHubCredentialStore().save(token)
        console.print(
            Panel(
                "[bold green]✓ GitHub authentication completed.[/bold green]\n\n"
                "Your credential was saved. You can now use "
                "[bold]sb publish github upload[/bold] to publish your site.\n\n"
                "To sign in again later, run [bold]sb publish github init[/bold].",
                title="[bold green]Ready to publish[/bold green]",
                border_style="green",
            )
        )
    except GitHubError as exc:
        console.print(
            Panel(
                f"[bold red]GitHub sign-in did not complete.[/bold red]\n\n{exc}\n\n"
                "Please try [bold]sb publish github init[/bold] again. "
                "Your existing credential, if any, was not replaced.",
                title="[bold red]Authentication problem[/bold red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1) from exc


@github_app.command()
def upload(dry_run: bool = typer.Option(False, "--dry-run", help="Show planned work without changing GitHub.")) -> None:
    """Upload the generated site to the user's starbash-public repository."""
    site = _rewrite()
    files = sorted(
        path
        for path in site.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".jekyll-cache" not in path.parts
        and "_site" not in path.parts
        and path.name != "github-auth.toml"
        and not any(
            path.relative_to(site).as_posix().startswith(prefix)
            for prefix in UPLOAD_PATH_BLACKLIST
        )
    )
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Publish Starbash images ({timestamp})"
    if dry_run:
        console.print(f"Dry run: {len(files)} files, gh-pages, {message}")
        for path in files:
            console.print(f"  {path.relative_to(site)} ({path.stat().st_size} bytes)")
        return
    token = GitHubCredentialStore().load()
    if not token:
        raise typer.BadParameter("No GitHub credential. Run 'sb publish github init'.")
    service = GitHubService(token)
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            operation = progress.add_task("Contacting GitHub", total=8 + len(files))

            owner = str(service.user()["login"])
            pages_url = f"https://{owner}.github.io/starbash-public/"
            progress.update(operation, description=f"Authenticated as {owner}", advance=1)
            repository = service.repository(owner, "starbash-public")
            progress.update(operation, description="Checked starbash-public repository", advance=1)
            if repository is None:
                repository = service.create_repository("starbash-public")
                progress.update(operation, description="Created starbash-public repository", advance=1)
            elif not service.branch_exists(owner, "starbash-public", "main"):
                console.print(
                    "[yellow]The GitHub repository is empty; creating its required initial commit.[/yellow]"
                )
                service.bootstrap_repository(
                    owner,
                    "starbash-public",
                    pages_url,
                )
                progress.update(operation, description="Initialized repository", advance=1)
            else:
                progress.update(operation, description="Repository is ready", advance=1)

            entries: list[dict[str, str]] = []
            for path in files:
                relative_path = path.relative_to(site).as_posix()
                blob = service.create_blob(owner, "starbash-public", path.read_bytes())
                entries.append({"path": relative_path, "mode": "100644", "type": "blob", "sha": blob})
                progress.update(operation, description=f"Uploaded {relative_path}", advance=1)
            tree = service.create_tree(owner, "starbash-public", entries)
            progress.update(operation, description="Created Git tree", advance=1)
            commit = service.create_commit(owner, "starbash-public", message, tree)
            progress.update(operation, description="Created publication commit", advance=1)
            service.update_branch(owner, "starbash-public", commit)
            progress.update(operation, description="Updated gh-pages", advance=1)
            service.configure_pages(owner, "starbash-public")
            progress.update(operation, description="Configured GitHub Pages", advance=1)
            progress.update(operation, description="GitHub Pages deployment complete", advance=1)
        console.print(f"Uploaded {len(files)} files to {pages_url}")
    except GitHubError as exc:
        raise typer.BadParameter(str(exc)) from exc
