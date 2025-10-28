import typer
from typing_extensions import Annotated

from starbash.app import Starbash
from starbash import console

app = typer.Typer(invoke_without_command=True)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show all repos including system repos"
    ),
):
    """
    Manage repositories.

    When called without a subcommand, lists all repositories.
    Use --verbose to show all repos including system/recipe repos.
    """
    # If no subcommand is invoked, run the list behavior
    if ctx.invoked_subcommand is None:
        with Starbash("repo-list") as sb:
            repos = sb.repo_manager.repos if verbose else sb.repo_manager.regular_repos
            for i, repo in enumerate(repos):
                if verbose:
                    # No numbers for verbose mode (system repos can't be removed)
                    console.print(f"{ repo.url } (kind={ repo.kind})")
                else:
                    # Show numbers for user repos (can be removed later)
                    console.print(f"{ i + 1:2}: { repo.url } (kind={ repo.kind})")


@app.command()
def add(path: str):
    """
    Add a repository. path is either a local path or a remote URL.
    """
    with Starbash("repo-add") as sb:
        sb.user_repo.add_repo_ref(path)
        # we don't yet write default config files at roots of repos, but it would be easy to add here
        # r.write_config()
        sb.user_repo.write_config()
        # FIXME, we also need to index the newly added repo!!!
        console.print(f"Added repository: {path}")


@app.command()
def remove(reponum: str):
    """
    Remove a repository by number (from list).
    Use 'starbash repo' to see the repository numbers.
    """
    with Starbash("repo-remove") as sb:
        try:
            # Parse the repo number (1-indexed)
            repo_index = int(reponum) - 1

            # Get only the regular (user-visible) repos
            regular_repos = sb.repo_manager.regular_repos

            if repo_index < 0 or repo_index >= len(regular_repos):
                console.print(
                    f"[red]Error: Repository number {reponum} is out of range. Valid range: 1-{len(regular_repos)}[/red]"
                )
                raise typer.Exit(code=1)

            # Get the repo to remove
            repo_to_remove = regular_repos[repo_index]
            repo_url = repo_to_remove.url

            # Remove the repo reference from user config
            sb.remove_repo_ref(repo_url)
            console.print(f"[green]Removed repository: {repo_url}[/green]")

        except ValueError:
            console.print(
                f"[red]Error: '{reponum}' is not a valid repository number. Please use a number from 'repo list'.[/red]"
            )
            raise typer.Exit(code=1)


@app.command()
def reindex(
    reponum: Annotated[
        str | None,
        typer.Argument(help="The repository number, if not specified reindex all."),
    ] = None,
    force: bool = typer.Option(
        default=False, help="Reread FITS headers, even if they are already indexed."
    ),
):
    """
    Reindex a repository by number.
    If no number is given, reindex all repositories.
    Use 'starbash repo' to see the repository numbers.
    """
    with Starbash("repo-reindex") as sb:
        if reponum is None:
            console.print("Reindexing all repositories...")
            sb.reindex_repos(force=force)
        else:
            try:
                # Parse the repo number (1-indexed)
                repo_index = int(reponum) - 1

                # Get only the regular (user-visible) repos
                regular_repos = sb.repo_manager.regular_repos

                if repo_index < 0 or repo_index >= len(regular_repos):
                    console.print(
                        f"[red]Error: Repository number {reponum} is out of range. Valid range: 1-{len(regular_repos)}[/red]"
                    )
                    raise typer.Exit(code=1)

                # Get the repo to reindex
                repo_to_reindex = regular_repos[repo_index]
                console.print(f"Reindexing repository: {repo_to_reindex.url}")
                sb.reindex_repo(repo_to_reindex, force=force)
                console.print(
                    f"[green]Successfully reindexed repository {reponum}[/green]"
                )

            except ValueError:
                console.print(
                    f"[red]Error: '{reponum}' is not a valid repository number. Please use a number from 'starbash repo'.[/red]"
                )
                raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
