"""Publish processed targets as a local Jekyll site."""

import typer

from starbash import console
from starbash.app import Starbash
from starbash.publish.github import GitHubPublisher

app = typer.Typer()


@app.callback(invoke_without_command=True)
def publish() -> None:
    """Generate a local GitHub Pages-compatible site from processed targets."""
    with Starbash("publish") as sb:
        site = GitHubPublisher(sb).publish()
        console.print(f"Generated site: {site}")
