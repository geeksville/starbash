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
    with Starbash() as sb:
        sb.user_repo.config["analytics.enabled"] = enable
        sb.user_repo.write_config()
        status = "enabled" if enable else "disabled"
        console.print(f"Analytics (crash reports) {status}.")
