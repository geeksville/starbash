import typer
from typing_extensions import Annotated
from pathlib import Path

from repo import repo_suffix
from starbash.app import Starbash
from starbash import console
from starbash.toml import toml_from_template

app = typer.Typer(invoke_without_command=True)


def repo_enumeration(sb: Starbash):
    """return a dict of int (1 based) to Repo instances"""
    verbose = False  # assume not verbose for enum picking
    repos = sb.repo_manager.repos if verbose else sb.repo_manager.regular_repos

    return {i + 1: repo for i, repo in enumerate(repos)}


def complete_repo_by_num(incomplete: str):
    with Starbash("repo.complete.num") as sb:
        for num, repo in repo_enumeration(sb).items():
            if str(num).startswith(incomplete):
                yield (str(num), repo.url)


@app.command()
def list(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show all repos including system repos"
    ),
):
    """
    lists all repositories.
    Use --verbose to show all repos including system/recipe repos.
    """
    with Starbash("repo.list") as sb:
        repos = sb.repo_manager.repos if verbose else sb.repo_manager.regular_repos
        for i, repo in enumerate(repos):
            kind = repo.kind("input")
            # for unknown repos (probably because we haven't written a starbash.toml file to the root yet),
            # we call them "input" because users will be less confused by that

            if verbose:
                # No numbers for verbose mode (system repos can't be removed)
                console.print(f"{ repo.url } (kind={ kind })")
            else:
                # Show numbers for user repos (can be removed later)
                console.print(f"{ i + 1:2}: { repo.url } (kind={ kind })")


@app.callback()
def main(
    ctx: typer.Context,
):
    """
    Manage repositories.

    When called without a subcommand, lists all repositories.
    """
    # If no subcommand is invoked, run the list behavior
    if ctx.invoked_subcommand is None:
        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def add(
    path: str,
    master: bool = typer.Option(
        False, "--master", help="Mark this new repository for master files."
    ),
):
    """
    Add a repository. path is either a local path or a remote URL.
    """
    repo_type = None
    if master:
        repo_type = "master"
    with Starbash("repo.add") as sb:
        p = Path(path)

        if repo_type:
            console.print(f"Creating {repo_type} repository: {p}")
            p.mkdir(parents=True, exist_ok=True)

            toml_from_template(
                f"repo/{repo_type}",
                p / repo_suffix,
                overrides={
                    "REPO_TYPE": repo_type,
                    "REPO_PATH": str(p),
                    "DEFAULT_RELATIVE": "{instrument}/{datetime}/{imagetyp}/{sessionconfig}.fits",
                },
            )
        else:
            # No type specified, therefore (for now) assume we are just using this as an input
            # repo (and it must exist)
            if not p.exists():
                console.print(f"[red]Error: Repo path does not exist: {p}[/red]")
                raise typer.Exit(code=1)

            console.print(f"Adding repository: {p}")

        repo = sb.user_repo.add_repo_ref(p)
        if repo:
            sb.reindex_repo(repo)

            # we don't yet write default config files at roots of repos, but it would be easy to add here
            # r.write_config()
            sb.user_repo.write_config()
            # FIXME, we also need to index the newly added repo!!!


@app.command()
def remove(
    reponum: Annotated[
        str,
        typer.Argument(help="Repository number", autocompletion=complete_repo_by_num),
    ],
):
    """
    Remove a repository by number (from list).
    Use 'starbash repo' to see the repository numbers.
    """
    with Starbash("repo.remove") as sb:
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
        typer.Argument(
            help="The repository number, if not specified reindex all.",
            autocompletion=complete_repo_by_num,
        ),
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
    with Starbash("repo.reindex") as sb:
        if reponum is None:
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
