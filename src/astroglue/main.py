import logging
import typer
from rich.logging import RichHandler

from astroglue.app import AstroGlue

app = typer.Typer()


def setup_logging():
    """
    Configures basic logging.
    """
    logging.basicConfig(
        level="INFO",  # don't print messages of lower priority than this
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


@app.command()
def main():
    """Main entry point for the astroglue application."""
    logging.info("astroglue starting up")

    with AstroGlue() as ag:
        pass


if __name__ == "__main__":
    setup_logging()
    app()
