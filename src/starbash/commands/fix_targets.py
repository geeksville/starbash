"""Upgrade processed targets to the current metadata layout."""

from pathlib import Path

import typer

from starbash.app import Starbash

app = typer.Typer()


def fix_targets() -> None:
    """Convert legacy processed targets to the .starbash metadata layout."""
    from starbash import console
    from starbash.target_migration import migrate_processed_repository

    with Starbash("fix-targets") as sb:
        repos = sb.repo_manager.get_repos_by_kind("processed")
        if len(repos) != 1:
            console.print(
                f"[red]Expected exactly one processed repository, found {len(repos)}.[/red]"
            )
            raise typer.Exit(1)

        repo_dir = repos[0].get_path()
        if repo_dir is None:
            console.print("[red]The processed repository must be local.[/red]")
            raise typer.Exit(1)

        try:
            converted, skipped = migrate_processed_repository(Path(repo_dir))
        except (OSError, ValueError) as exc:
            console.print(f"[red]Unable to fix processed targets: {exc}[/red]")
            raise typer.Exit(1) from exc

        console.print(
            f"[green]Converted {converted} processed target(s); "
            f"skipped {skipped} already-upgraded target(s).[/green]"
        )
