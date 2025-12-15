from typing import Any, NoReturn


class NonSoftwareError(Exception):
    """An error outside the control of the software, exit the app with an error code, but no need to
    report it as a software bug.

    Used for OS errors etc after we've determined we can't do anything more useful."""

    def __rich__(self) -> Any:
        return self.__str__()  # At least this is something readable...


class UserHandledError(NonSoftwareError):
    """An exception that terminates processing of the current file, but we want to help the user fix the problem."""

    def ask_user_handled(self) -> bool:
        """Prompt the user with a friendly message about the error.
        Returns:
            True if the error was handled, False otherwise.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        console.print(f"Error: {self}")
        return False


def raise_missing_repo(kind: str) -> NoReturn:
    """Raise a UserHandledError indicating that a repository of the given kind is missing."""
    raise UserHandledError(
        f"No {kind} repo configured.  Run 'sb user setup' (recommended) or 'sb repo add --{kind} <path>' to add one."
    )


class NonFatalException(ValueError):
    """An exception that means we have to skip the current stage/task, but don't tell the user"""


class NotEnoughFilesError(NonFatalException):
    """Exception raised when not enough input files are provided for a processing stage."""

    def __init__(self, message: str, files: list[str] = []):
        super().__init__(message)
        self.files = files


class NoSuitableMastersException(NonFatalException):
    """Exception raised when no suitable master calibration files are found."""

    def __init__(self, kind: str):
        super().__init__(f"No suitable master calibration files found for kind: {kind}")
        self.kind = kind


__all__ = [
    "UserHandledError",
    "NonFatalException",
    "NotEnoughFilesError",
    "NoSuitableMastersException",
    "raise_missing_repo",
]
