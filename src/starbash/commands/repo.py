import typer
from typing_extensions import Annotated

from starbash.app import Starbash
from starbash import console

app = typer.Typer()


@app.command()
def add(path: str):
    """
    Add a repository. path is either a local path or a remote URL.
    """
    with Starbash() as sb:
        sb.user_repo.add_repo_ref(path)
        # we don't yet write default config files at roots of repos, but it would be easy to add here
        # r.write_config()
        sb.user_repo.write_config()
        # FIXME, we also need to index the newly added repo!!!
        console.print(f"Added repository: {path}")


@app.command()
def remove(reponame: str):
    """
    Remove a repository by name or number.
    """
    raise


@app.command()
def list():
    """
    List all repositories.  The listed names/numbers can be used with other commands.
    """
    with Starbash() as sb:
        for i, repo in enumerate(sb.repo_manager.repos):
            console.print(f"{ i + 1:2}: { repo.url } (kind={ repo.kind})")


@app.command()
def reindex(
    repo: Annotated[
        str | None,
        typer.Argument(
            help="The repository name or number, if not specified reindex all."
        ),
    ] = None,
    force: bool = typer.Option(
        default=False, help="Reread FITS headers, even if they are already indexed."
    ),
):
    """
    Reindex the named repository.
    If no name is given, reindex all repositories.
    """
    with Starbash() as sb:
        if repo is None:
            console.print("Reindexing all repositories...")
            sb.reindex_repos(force=force)
        else:
            raise NotImplementedError("Reindexing a single repo not yet implemented.")


if __name__ == "__main__":
    app()
