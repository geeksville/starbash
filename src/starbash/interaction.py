"""Injectable user interaction for guided flows.

Commands such as ``sb user setup`` occasionally need to ask the user a question
or open a URL.  Reading directly from stdin is fine for the CLI, but the optional
desktop GUI (``sb gui``) must instead render native dialogs.

This module defines:

* :class:`UserInteraction` - the small protocol commands depend on.
* :class:`RichUserInteraction` - the default, which reproduces the CLI's existing
  Rich prompt behaviour *exactly* (so plain terminal usage is unchanged).
* :class:`AutoAcceptUserInteraction` - a headless implementation that always
  answers the default, useful for automation and tests.
* :func:`get_interaction` / :func:`set_interaction` - a process-wide accessor so a
  command can be driven by whichever front end is currently active.
"""

from __future__ import annotations

import logging
import webbrowser
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

__all__ = [
    "UserInteraction",
    "RichUserInteraction",
    "AutoAcceptUserInteraction",
    "get_interaction",
    "set_interaction",
]


class UserInteraction(ABC):
    """The set of questions a guided command may ask its front end."""

    @abstractmethod
    def confirm(self, prompt: str, default: bool = True) -> bool:
        """Ask a yes/no question and return the answer."""

    @abstractmethod
    def text(self, prompt: str, default: str = "", show_default: bool = True) -> str:
        """Ask for a line of text and return it (``default`` when blank)."""

    @abstractmethod
    def notify(self, message: str) -> None:
        """Show an informational message to the user."""

    def open_url(self, url: str) -> bool:
        """Try to open ``url`` in the user's browser.

        Returns:
            ``True`` if a browser was launched, ``False`` otherwise.  The
            default implementation delegates to :mod:`webbrowser`.
        """
        try:
            return bool(webbrowser.open(url))
        except (OSError, webbrowser.Error):
            return False


class RichUserInteraction(UserInteraction):
    """The terminal default: prompts via Rich, exactly like the legacy CLI."""

    def confirm(self, prompt: str, default: bool = True) -> bool:
        from rich.prompt import Confirm

        from starbash import console

        return Confirm.ask(prompt, default=default, console=console)

    def text(self, prompt: str, default: str = "", show_default: bool = True) -> str:
        from rich.prompt import Prompt

        from starbash import console

        return Prompt.ask(prompt, default=default, show_default=show_default, console=console)

    def notify(self, message: str) -> None:
        from starbash import console

        console.print(message)


class AutoAcceptUserInteraction(UserInteraction):
    """Headless interaction that answers every prompt with its default.

    Used by automation and tests so a guided flow can run start-to-finish without
    a human.  ``notify`` messages are logged instead of printed.
    """

    def confirm(self, prompt: str, default: bool = True) -> bool:
        logger.info("auto-accept confirm(%r) -> %s", prompt, default)
        return default

    def text(self, prompt: str, default: str = "", show_default: bool = True) -> str:
        logger.info("auto-accept text(%r) -> %r", prompt, default)
        return default

    def notify(self, message: str) -> None:
        logger.info("notify: %s", message)

    def open_url(self, url: str) -> bool:
        logger.info("auto-accept open_url(%s)", url)
        return False


# Default to the CLI's Rich behaviour; the GUI replaces this on startup.
_instance: UserInteraction = RichUserInteraction()


def get_interaction() -> UserInteraction:
    """Return the interaction implementation currently in effect."""
    return _instance


def set_interaction(interaction: UserInteraction | None) -> None:
    """Install ``interaction`` process-wide (``None`` restores the Rich default)."""
    global _instance
    _instance = interaction if interaction is not None else RichUserInteraction()
