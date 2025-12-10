"""Python tool integration using RestrictedPython."""

import io
import logging
import os

import RestrictedPython
from rich.traceback import Traceback

from starbash.exception import UserHandledError
from starbash.tool.base import Tool
from starbash.tool.context import make_safe_globals

logger = logging.getLogger(__name__)

__all__ = ["PythonTool", "PythonScriptError"]


class PythonScriptError(UserHandledError):
    """Exception raised when an error occurs during Python script execution."""

    def ask_user_handled(self) -> bool:
        """Prompt the user with a friendly message about the error.
        Returns:
            True if the error was handled, False otherwise.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        console.print(
            """[bold red]Python Script Error[/bold red] please contact the script author and
            give them this information.

            Processing for the current file will be skipped..."""
        )

        # Show the traceback with Rich formatting
        if self.__cause__:
            traceback = Traceback.from_exception(
                type(self.__cause__),
                self.__cause__,
                self.__cause__.__traceback__,
                show_locals=True,
            )
            console.print(traceback)
        else:
            console.print(f"[yellow]{str(self)}[/yellow]")

        return True


class PythonTool(Tool):
    """Expose Python as a tool"""

    def __init__(self) -> None:
        super().__init__("python")

        # default script file override
        self.default_script_file = "starbash.py"

    def _run(
        self, cwd: str, commands: str, context: dict = {}, log_out: io.TextIOWrapper | None = None
    ) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(cwd)  # cd to where this script expects to run

            # FIXME, we currently ignore log_out because python is by default printing to our log anyways
            logger.info(f"Executing python script in {cwd} using RestrictedPython")
            try:
                byte_code = RestrictedPython.compile_restricted(
                    commands, filename="<python script>", mode="exec"
                )
                # No locals yet
                execution_locals = None
                globals = {"context": context}
                exec(byte_code, make_safe_globals(globals), execution_locals)
            except SyntaxError as e:
                raise PythonScriptError("Syntax error in python script") from e
            except UserHandledError:
                raise  # No need to wrap this - just pass it through for user handling
            except Exception as e:
                raise PythonScriptError("Error during python script execution") from e
        finally:
            os.chdir(original_cwd)
