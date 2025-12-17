"""Python tool integration using RestrictedPython."""

import ast
import io
import linecache
import logging
import os
import traceback
from typing import Any

import RestrictedPython
from RestrictedPython.Guards import INSPECT_ATTRIBUTES
from RestrictedPython.transformer import ALLOWED_FUNC_NAMES, FORBIDDEN_FUNC_NAMES, copy_locations

from starbash.exception import UserHandledError
from starbash.sim_siril.connection import SirilInterface
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

        message = str(self)
        bt = ""
        if self.__cause__:
            bt = "Traceback" + "  \n".join(
                traceback.format_exception(self.__cause__)
                )

        console.print(
            f"""[red]Python Script Error[/red] please contact the script author and
            give them this information: Error: [red]{message}[/red]
            {bt}

            Processing for the current file will be skipped..."""
        )

        # way too verbose (but pretty colors)
        # Show the traceback with Rich formatting
        #if self.__cause__:
        #    traceback = Traceback.from_exception(
        #        type(self.__cause__),
        #        self.__cause__,
        #        self.__cause__.__traceback__,
        #        show_locals=True,
        #    )
        #    console.print(traceback)
        #else:
        #    console.print(f"[yellow]{str(self)}[/yellow]")

        return True


class PermissiveNodeTransformer(RestrictedPython.RestrictingNodeTransformer):
    """FIXME we temporarily allow more access than RestrictedPython usually grants"""

    def check_name(self, node, name, allow_magic_methods=False):
        """Check names if they are allowed.

        If ``allow_magic_methods is True`` names in `ALLOWED_FUNC_NAMES`
        are additionally allowed although their names start with `_`.

        """
        if name is None:
            return

        # FIXME, nasty hack to allow __name__ to work in our test of siril scripts
        allow_magic_methods= True

        allowed_func_names = set(ALLOWED_FUNC_NAMES)
        allowed_func_names.add('__name__')

        if (name.startswith('_')
                and name != '_'
                and not (allow_magic_methods
                         and name in allowed_func_names
                         and node.col_offset != 0)):
            self.error(
                node,
                f'"{name}" is an invalid variable name because it '
                'starts with "_"')
        elif name.endswith('__roles__'):
            self.error(node, '"%s" is an invalid variable name because it ends with "__roles__".' % name)  # noqa: UP031
        elif name in FORBIDDEN_FUNC_NAMES:
            self.error(node, f'"{name}" is a reserved name.')

    def visit_Attribute(self, node):
        """Checks and mutates attribute access/assignment.

        'a.b' becomes '_getattr_(a, "b")'
        'a.b = c' becomes '_write_(a).b = c'
        'del a.b' becomes 'del _write_(a).b'

        The _write_ function should return a security proxy.
        """
        # FIXME - disabled so that __init__ and others can be used in scripts
        #if node.attr.startswith('_') and node.attr != '_':
        #    self.error(
        #        node,
        #        f'"{node.attr}" is an invalid attribute name because it starts '
        #        'with "_".')

        if node.attr.endswith('__roles__'):
            self.error(
                node,
                f'"{node.attr}" is an invalid attribute name because it ends '
                'with "__roles__".')

        if node.attr in INSPECT_ATTRIBUTES:
            self.error(
                node,
                f'"{node.attr}" is a restricted name,'
                ' that is forbidden to access in RestrictedPython.',
            )

        if isinstance(node.ctx, ast.Load):
            node = self.node_contents_visit(node)
            new_node = ast.Call(
                func=ast.Name('_getattr_', ast.Load()),
                args=[node.value, ast.Constant(node.attr)],  # pyright: ignore[reportAttributeAccessIssue]
                keywords=[])

            copy_locations(new_node, node)
            return new_node

        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            node = self.node_contents_visit(node)
            new_value = ast.Call(
                func=ast.Name('_write_', ast.Load()),
                args=[node.value],  # pyright: ignore[reportAttributeAccessIssue]
                keywords=[])

            copy_locations(new_value, node.value)  # pyright: ignore[reportAttributeAccessIssue]
            node.value = new_value  # pyright: ignore[reportAttributeAccessIssue]
            return node

        else:  # pragma: no cover
            # Impossible Case only ctx Load, Store and Del are defined in ast.
            raise NotImplementedError(
                f"Unknown ctx type: {type(node.ctx)}")

class PythonTool(Tool):
    """Expose Python as a tool"""

    def __init__(self) -> None:
        super().__init__("python")

        # default script file override
        self.default_script_file = "starbash.py"

    def _run(
        self, cwd: str, commands: str, context: dict = {}, log_out: io.TextIOWrapper | None = None, **kwargs: dict[str, Any]
    ) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(cwd)  # cd to where this script expects to run

            # FIXME, we currently ignore log_out because python is by default printing to our log anyways
            logger.info(f"Executing python script in {cwd} using RestrictedPython")
            try:
                # Hopefully the user provided a filepath
                script_filename = kwargs.get("script_file", "<python script>")
                assert isinstance(script_filename, str)

                # Cache the source code so tracebacks show proper line numbers
                lines = commands.splitlines(keepends=True)
                linecache.cache[script_filename] = (
                    len(commands),
                    None,
                    lines,
                    script_filename
                )

                byte_code = RestrictedPython.compile_restricted(
                    commands, filename=script_filename, mode="exec", policy=PermissiveNodeTransformer
                )
                # No locals yet
                execution_locals = None
                globals = {"context": context}

                # Tell our sim Siril interface about the context too
                SirilInterface.Context = context

                exec(byte_code, make_safe_globals(globals), execution_locals)
            except SyntaxError as e:
                raise PythonScriptError(f"[red]Script syntax error[/red]: {e}") from e
            except UserHandledError:
                raise  # No need to wrap this - just pass it through for user handling
            except Exception as e:
                raise PythonScriptError(f"[red]Python script error[/red]: {e}") from e
        finally:
            os.chdir(original_cwd)
