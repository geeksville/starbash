class UserHandledError(ValueError):
    """An exception that terminates processing of the current file, but we want to help the user fix the problem."""

    def ask_user_handled(self) -> bool:
        """Prompt the user with a friendly message about the error.
        Returns:
            True if the error was handled, False otherwise.
        """
        raise NotImplementedError("Subclasses must implement ask_user_handled method.")


__all__ = ["UserHandledError"]
