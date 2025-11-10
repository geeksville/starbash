from textwrap import dedent
from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from starbash.app import Starbash
from starbash.paths import get_user_documents_dir

app = typer.Typer()


@app.command()
def analytics(
    enable: Annotated[
        bool,
        typer.Argument(
            help="Enable or disable analytics (crash reports and usage data).",
        ),
    ],
):
    """
    Enable or disable analytics (crash reports and usage data).
    """
    with Starbash("analytics.change") as sb:
        from starbash import console

        sb.analytics.set_data("analytics.enabled", enable)
        sb.user_repo.set("analytics.enabled", enable)
        sb.user_repo.write_config()
        status = "enabled" if enable else "disabled"
        console.print(f"Analytics (crash reports) {status}.")


@app.command()
def name(
    user_name: Annotated[
        str,
        typer.Argument(
            help="Your name for attribution in generated images.",
        ),
    ],
):
    """
    Set your name for attribution in generated images.
    """
    with Starbash("user.name") as sb:
        from starbash import console

        sb.user_repo.set("user.name", user_name)
        sb.user_repo.write_config()
        console.print(f"User name set to: {user_name}")


@app.command()
def email(
    user_email: Annotated[
        str,
        typer.Argument(
            help="Your email for attribution in generated images.",
        ),
    ],
):
    """
    Set your email for attribution in generated images.
    """
    with Starbash("user.email") as sb:
        from starbash import console

        sb.user_repo.set("user.email", user_email)
        sb.user_repo.write_config()
        console.print(f"User email set to: {user_email}")


def _ask_masters(sb: Starbash) -> None:
    from starbash import console

    has_masters = sb.repo_manager.get_repo_by_kind("master") is not None
    if not has_masters:
        want_default_dirs = Confirm.ask(
            dedent("""
            Would you like to create default output directories in your Documents folder
            (recommended - you can change this later with [cyan]'sb repo ...'[/cyan])?
            """),
            default=True,
            console=console,
        )
        if want_default_dirs:
            console.print("Creating default repositories...")
            master_path = str(get_user_documents_dir() / "repos" / "master")
            processed_path = str(get_user_documents_dir() / "repos" / "processed")
            sb.add_local_repo(path=master_path, repo_type="master")
            sb.add_local_repo(path=processed_path, repo_type="processed")
            console.print(f"✅ Created master repository at: {master_path}")
            console.print(f"✅ Created processed repository at: {processed_path}")
            console.print()


def _ask_user_config(sb: Starbash) -> None:
    from starbash import console

    # Ask for username
    user_name = Prompt.ask(
        "Enter your name (for attribution in generated images)",
        default=sb.user_repo.get("user.name", ""),
        show_default=False,
        console=console,
    )
    sb.analytics.set_data("analytics.use_name", user_name != "")
    if user_name:
        sb.user_repo.set("user.name", user_name)
        console.print(f"✅ Name set to: {user_name}")
    else:
        console.print("[dim]Skipped name[/dim]")

    # Ask for email
    user_email = Prompt.ask(
        "Enter your email address (for attribution in generated images)",
        default=sb.user_repo.get("user.email", ""),
        show_default=False,
        console=console,
    )
    sb.analytics.set_data("analytics.use_email", user_email != "")
    if user_email:
        sb.user_repo.set("user.email", user_email)
        console.print(f"✅ Email set to: {user_email}")
    else:
        console.print("[dim]Skipped email[/dim]")

    # Ask about including email in crash reports
    include_in_reports = Confirm.ask(
        "Would you like to include your email address with crash reports/analytics?\n"
        "(This helps us follow up if we need more information about issues.)",
        default=sb.user_repo.get("analytics.include_user", False),
        console=console,
    )
    sb.analytics.set_data("analytics.use_email_report", include_in_reports)
    sb.user_repo.set("analytics.include_user", include_in_reports)
    if include_in_reports:
        console.print("✅ Email will be included with crash reports")
    else:
        console.print("❌ Email will NOT be included with crash reports")
    console.print()

    # Save all changes
    sb.user_repo.write_config()


def do_reinit(sb: Starbash) -> None:
    from starbash import console

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Starbash getting started...[/bold cyan]\n\n"
            "Let's do your first time setup.  You can skip any question by pressing Enter.\n"
            "If you need to re-run this setup later, just run: [cyan]'sb user setup'[/cyan]",
            border_style="cyan",
        )
    )
    console.print()
    console.print()
    _ask_user_config(sb)
    _ask_masters(sb)

    console.print(
        Panel.fit(
            dedent("""
            [bold green]Basic setup is complete[/bold green]
            You are almost ready to start using Starbash!

            Recommended next steps (to get your first auto-generated images):
            1. Add your source raw image repositories (starbash will only READ from these):
               [cyan]sb repo add /path/to/your/raw_images[/cyan]
            2. Ask starbash to auto-generate 'master' darks, biases and flats:
                [cyan]sb process masters[/cyan]
            3. Process your images using automated workflows:
                [cyan]sb process auto[/cyan]
            4. (Highly recommended) Tell your shell to auto-complete starbash commands:
                [cyan]sb shell-complete --install-completion[/cyan]

            This project is currently very 'alpha' but we are eager to have it work for you.
            For full instructions and support [link=https://github.com/geeksville/starbash]visit our github[/link].
            If you find problems or have questions, just open an issue and we'll work with you.
            """),
            border_style="green",
            title="Almost done!",
        )
    )


@app.command()
def setup():
    """
    Configure starbash via a brief guided process.

    This will ask you for your name, email, and analytics preferences.
    You can skip any question by pressing Enter.
    """
    with Starbash("user.setup") as sb:
        do_reinit(sb)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Main callback for the Starbash application."""
    if ctx.invoked_subcommand is None:
        from starbash import console

        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()
