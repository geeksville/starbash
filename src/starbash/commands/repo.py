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
    pass


@app.command()
def remove(reponame: str):
    """
    Remove a repository by name or number.
    """
    pass


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
    reponame: Annotated[
        str,
        typer.Argument(help="The repository name or number, or none to reindex all."),
    ],
):
    """
    Reindex the named repository.
    If no name is given, reindex all repositories.
    """
    pass


if __name__ == "__main__":
    app()
