import typer
from typing_extensions import Annotated

from starbash.app import Starbash
from starbash import console

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
    with Starbash("analytics-enable") as sb:
        sb.analytics.set_data("analytics.enabled", enable)
        sb.user_repo.config["analytics.enabled"] = enable
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
    with Starbash("user-name") as sb:
        sb.user_repo.config["user.name"] = user_name
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
    with Starbash("user-email") as sb:
        sb.user_repo.config["user.email"] = user_email
        sb.user_repo.write_config()
        console.print(f"User email set to: {user_email}")
