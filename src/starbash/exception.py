from typing import Any


class UserHandledError(ValueError):
    """An exception that terminates processing of the current file, but we want to help the user fix the problem."""

    def ask_user_handled(self) -> bool:
        """Prompt the user with a friendly message about the error.
        Returns:
            True if the error was handled, False otherwise.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        console.print(f"Error: {self}")
        return False

    def __rich__(self) -> Any:
        return self.__str__()  # At least this is something readable...


__all__ = ["UserHandledError"]
