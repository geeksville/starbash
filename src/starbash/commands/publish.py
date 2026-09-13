"""Publish processed targets locally or to GitHub Pages."""

import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from starbash import console
from starbash.analytics import analytics_start_span
from starbash.app import Starbash
from starbash.publish.credentials import GitHubCredential, GitHubCredentialStore
from starbash.publish.github import GitHubPublisher
from starbash.publish.github_publish import (
    APP_INSTALLATION_URL,
    APP_SLUG,
    CLIENT_ID,
    collect_site_files,
    credential_service,
    finish_device_login,
    publish_site,
    refresh_if_needed,
    save_credential,
)
from starbash.publish.github_service import GitHubError, GitHubService

app = typer.Typer()
github_app = typer.Typer()
app.add_typer(github_app, name="github")


def _rewrite(github_username: str | None = None) -> Path:
    site: Path | None = None
    with Starbash("publish.github.rewrite") as sb:
        site = GitHubPublisher(sb, github_username=github_username).publish()
    assert site is not None
    console.print(f"Generated site: {site}")
    return site


def _open_app_installation() -> None:
    """Explain GitHub App installation and open GitHub's installation page."""
    console.print(
        Panel(
            "[bold]GitHub authorization is complete, but the Starbash GitHub App "
            "is not installed yet.[/bold]\n\n"
            "GitHub requires these two separate steps. Please:\n"
            "  [cyan]1.[/cyan] Open the installation page below.\n"
            "  [cyan]2.[/cyan] Select your personal GitHub account.\n"
            "  [cyan]3.[/cyan] Choose [bold]All repositories[/bold]. This lets Starbash "
            "create and publish its `starbash-public` repository.\n"
            "  [cyan]4.[/cyan] Click [bold]Install[/bold].\n"
            "  [cyan]5.[/cyan] Return to Starbash.\n\n"
            f"[link={APP_INSTALLATION_URL}]{APP_INSTALLATION_URL}[/link]",
            title="[bold yellow]One more GitHub step[/bold yellow]",
            border_style="yellow",
        )
    )
    typer.prompt(
        "Press Enter to open the GitHub installation page",
        default="",
        show_default=False,
    )
    try:
        opened = webbrowser.open(APP_INSTALLATION_URL)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        console.print(
            "[yellow]⚠ I could not open a browser automatically. "
            "Please open the link above manually.[/yellow]"
        )


def _require_app_installation(service: GitHubService) -> None:
    """Guide the user through installation when the GitHub App is not installed."""
    if service.app_is_installed(APP_SLUG):
        return
    _open_app_installation()
    typer.prompt(
        "After clicking Install on GitHub, press Enter here to check the installation",
        default="",
        show_default=False,
    )
    if not service.app_is_installed(APP_SLUG):
        raise GitHubError(
            "The Starbash GitHub App is still not installed. "
            "Install it from the link above, then run this command again."
        )


@github_app.command()
def rewrite() -> None:
    """Regenerate the local GitHub Pages-compatible site."""
    _rewrite()


def _authenticate() -> GitHubCredential:
    """Run Device Authorization Flow and save a new GitHub credential."""
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
        "  [cyan]2.[/cyan] A browser page will ask you to approve the Starbash application.\n"
        "  [cyan]3.[/cyan] You will enter the displayed code on that page.\n"
        "  [cyan]4.[/cyan] GitHub will ask you to install the app; choose your account "
        "and [bold]All repositories[/bold].\n"
        "  [cyan]5.[/cyan] Starbash will save the resulting credential in your "
        "operating system's credential store.\n"
        "\n[dim]Your GitHub password is never entered into Starbash and is never "
        "shared with Starbash.[/dim]"
    )
    with analytics_start_span(name="github", op="init"):
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
                    "open automatically, copy the link above into your browser.\n\n"
                    "Press Enter when you are ready; the browser may open in front "
                    "of this terminal.",
                    title="[bold yellow]Authorize Starbash on GitHub[/bold yellow]",
                    border_style="yellow",
                )
            )
            typer.prompt(
                "Press Enter to open the GitHub verification page",
                default="",
                show_default=False,
            )
            try:
                opened = webbrowser.open(device.verification_uri)
            except (OSError, webbrowser.Error):
                opened = False
            if opened:
                console.print("[green]✓[/green] I opened the verification page. ")
            else:
                console.print(
                    "[yellow]⚠ I could not open a browser automatically.[/yellow] "
                    "Please open the printed link manually."
                )
            with console.status("[bold cyan]Waiting for GitHub authorization…[/bold cyan]"):
                credential = finish_device_login(service, device, CLIENT_ID)
            authenticated_service = GitHubService(credential.access_token)
            if not authenticated_service.app_is_installed(APP_SLUG):
                with console.status("[bold cyan]Checking GitHub App installation…[/bold cyan]"):
                    _require_app_installation(authenticated_service)
            save_credential(credential, store=GitHubCredentialStore())
            console.print(
                Panel(
                    "[bold green]✓ GitHub authentication completed.[/bold green]\n\n"
                    "Your credential was saved. Starbash is ready to continue.",
                    title="[bold green]Ready to publish[/bold green]",
                    border_style="green",
                )
            )
            return credential
        except GitHubError as exc:
            console.print(
                Panel(
                    f"[bold red]GitHub sign-in did not complete.[/bold red]\n\n{exc}\n\n"
                    "Please try [bold]sb publish github --login[/bold] again. "
                    "Your existing credential, if any, was not replaced.",
                    title="[bold red]Authentication problem[/bold red]",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1) from exc


def _credential_service(credential: GitHubCredential) -> GitHubService:
    """Create an authenticated service and persist any rotated token."""
    return credential_service(credential, client_id=CLIENT_ID, store=GitHubCredentialStore())


def _publish_github(dry_run: bool, login: bool) -> None:
    """Generate and optionally publish the GitHub Pages site."""
    credential: GitHubCredential | None = None
    if not dry_run or login:
        if login:
            credential = _authenticate()
        else:
            credential = GitHubCredentialStore().load()
            if credential is None:
                credential = _authenticate()

    service: GitHubService | None = None
    owner: str | None = None
    if not dry_run:
        assert credential is not None
        service = _credential_service(credential)
        owner = str(service.user()["login"])
        refresh_if_needed(service, credential, client_id=CLIENT_ID)

    site = _rewrite(owner) if owner else _rewrite()
    files = collect_site_files(site)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Publish Starbash images ({timestamp})"
    if dry_run:
        console.print(f"Dry run: {len(files)} files, gh-pages, {message}")
        for path in files:
            console.print(f"  {path.relative_to(site)} ({path.stat().st_size} bytes)")
        console.print("No GitHub repository, branch, commit, or Pages configuration was changed.")
        return
    assert credential is not None
    assert service is not None
    assert owner is not None
    with analytics_start_span(name="github", op="upload"):
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                operation = progress.add_task("Contacting GitHub", total=10 + len(files))

                def on_step(description: str, _completed: int, _total: int) -> None:
                    progress.update(operation, description=description, advance=1)

                # The CLI has already offered to install the App (in _authenticate, or
                # via _require_app_installation below) with its own Rich prompts.
                _require_app_installation(service)
                result = publish_site(
                    service,
                    owner,
                    site,
                    files,
                    message=message,
                    require_app=False,
                    on_step=on_step,
                )
            console.print(
                f"Uploaded {result.file_count} files to {result.pages_url} ... "
                "It should be live in a few minutes."
            )
        except GitHubError as exc:
            raise typer.BadParameter(str(exc)) from exc


@github_app.callback(invoke_without_command=True)
def github(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show planned work without changing GitHub.",
    ),
    login: bool = typer.Option(
        False,
        "--login",
        help="Run GitHub sign-in before generating or publishing the site.",
    ),
) -> None:
    """Generate and publish the GitHub Pages site."""
    if ctx.invoked_subcommand is not None:
        if dry_run or login:
            raise typer.BadParameter("--dry-run and --login apply only to 'sb publish github'.")
        return
    _publish_github(dry_run, login)
