from typing import Annotated

import typer
from rich.panel import Panel

from starbash import console
from starbash.app import Starbash

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
        sb.user_repo.set("user.email", user_email)
        sb.user_repo.write_config()
        console.print(f"User email set to: {user_email}")


def do_reinit(sb: Starbash) -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Starbash getting started...[/bold cyan]\n\n"
            "Let's set up your preferences. You can skip any question by pressing Enter.",
            border_style="cyan",
        )
    )
    console.print()

    # Ask for username
    user_name = typer.prompt(
        "Enter your name (for attribution in generated images)",
        default="",
        show_default=False,
    )
    sb.analytics.set_data("analytics.use_name", user_name != "")
    if user_name:
        sb.user_repo.set("user.name", user_name)
        console.print(f"✅ Name set to: {user_name}")
    else:
        console.print("[dim]Skipped name[/dim]")

    # Ask for email
    user_email = typer.prompt(
        "Enter your email address (for attribution in generated images)",
        default="",
        show_default=False,
    )
    sb.analytics.set_data("analytics.use_email", user_email != "")
    if user_email:
        sb.user_repo.set("user.email", user_email)
        console.print(f"✅ Email set to: {user_email}")
    else:
        console.print("[dim]Skipped email[/dim]")

    # Ask about including email in crash reports
    include_in_reports = typer.confirm(
        "Would you like to include your email address with crash reports/analytics? "
        "(This helps us follow up if we need more information about issues.)",
        default=False,
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

    console.print(
        Panel.fit(
            "[bold green]Configuration complete![/bold green]\n\n"
            "Your preferences have been saved.",
            border_style="green",
        )
    )


@app.command()
def reinit():
    """
    Configure starbash via a brief guided process.

    This will ask you for your name, email, and analytics preferences.
    You can skip any question by pressing Enter.
    """
    with Starbash("user.reinit") as sb:
        do_reinit(sb)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Main callback for the Starbash application."""
    if ctx.invoked_subcommand is None:
        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()
