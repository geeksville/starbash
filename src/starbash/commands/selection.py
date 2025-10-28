"""Selection commands for filtering sessions and targets."""

import typer
from typing_extensions import Annotated
from rich.table import Table

from starbash.app import Starbash
from starbash import console

app = typer.Typer()


@app.command(name="any")
def clear():
    """Remove any filters on sessions, etc... (select everything)."""
    with Starbash("selection-clear") as sb:
        sb.selection.clear()
        console.print("[green]Selection cleared - now selecting all sessions[/green]")


@app.command()
def target(
    target_name: Annotated[
        str,
        typer.Argument(
            help="Target name to add to the selection (e.g., 'M31', 'NGC 7000')"
        ),
    ],
):
    """Limit the current selection to only the named target."""
    with Starbash("selection-target") as sb:
        # For now, replace existing targets with this one
        # In the future, we could support adding multiple targets
        sb.selection.targets = []
        sb.selection.add_target(target_name)
        console.print(f"[green]Selection limited to target: {target_name}[/green]")


@app.command()
def telescope(
    telescope_name: Annotated[
        str,
        typer.Argument(
            help="Telescope name to add to the selection (e.g., 'Vespera', 'EdgeHD 8')"
        ),
    ],
):
    """Limit the current selection to only the named telescope."""
    with Starbash("selection-telescope") as sb:
        # For now, replace existing telescopes with this one
        # In the future, we could support adding multiple telescopes
        sb.selection.telescopes = []
        sb.selection.add_telescope(telescope_name)
        console.print(
            f"[green]Selection limited to telescope: {telescope_name}[/green]"
        )


@app.command()
def date(
    operation: Annotated[
        str,
        typer.Argument(help="Date operation: 'after', 'before', or 'between'"),
    ],
    date_value: Annotated[
        str,
        typer.Argument(
            help="Date in ISO format (YYYY-MM-DD) or two dates separated by space for 'between'"
        ),
    ],
    end_date: Annotated[
        str | None,
        typer.Argument(help="End date for 'between' operation (YYYY-MM-DD)"),
    ] = None,
):
    """Limit to sessions in the specified date range.

    Examples:
        starbash selection date after 2023-10-01
        starbash selection date before 2023-12-31
        starbash selection date between 2023-10-01 2023-12-31
    """
    with Starbash("selection-date") as sb:
        operation = operation.lower()

        if operation == "after":
            sb.selection.set_date_range(start=date_value, end=None)
            console.print(
                f"[green]Selection limited to sessions after {date_value}[/green]"
            )
        elif operation == "before":
            sb.selection.set_date_range(start=None, end=date_value)
            console.print(
                f"[green]Selection limited to sessions before {date_value}[/green]"
            )
        elif operation == "between":
            if not end_date:
                console.print(
                    "[red]Error: 'between' operation requires two dates[/red]"
                )
                raise typer.Exit(1)
            sb.selection.set_date_range(start=date_value, end=end_date)
            console.print(
                f"[green]Selection limited to sessions between {date_value} and {end_date}[/green]"
            )
        else:
            console.print(
                f"[red]Error: Unknown operation '{operation}'. Use 'after', 'before', or 'between'[/red]"
            )
            raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def show_selection(ctx: typer.Context):
    """List information about the current selection.

    This is the default command when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        with Starbash("selection-show") as sb:
            summary = sb.selection.summary()

            if summary["status"] == "all":
                console.print(f"[yellow]{summary['message']}[/yellow]")
            else:
                table = Table(title="Current Selection")
                table.add_column("Criteria", style="cyan")
                table.add_column("Value", style="green")

                for criterion in summary["criteria"]:
                    parts = criterion.split(": ", 1)
                    if len(parts) == 2:
                        table.add_row(parts[0], parts[1])
                    else:
                        table.add_row(criterion, "")

                console.print(table)
