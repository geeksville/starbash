"""Context expansion utilities for tool templates."""

import importlib
import logging
import re
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import RestrictedPython

logger = logging.getLogger(__name__)

__all__ = [
    "_SafeFormatter",  # Exported for tests
    "expand_context",
    "expand_context_unsafe",
    "expand_context_list",
    "make_safe_globals",
    "strip_comments",
]


class _SafeFormatter(dict):
    """A dictionary for safe string formatting that ignores missing keys during expansion."""

    def __missing__(self, key):
        return "{" + key + "}"


def expand_context(s: str, context: dict) -> str:
    """Expand any named variables in the provided string

    Will expand strings of the form MyStr{somevar}a{someothervar} using vars listed in context.
    Guaranteed safe, doesn't run any python scripts.
    """
    # Iteratively expand the command string to handle nested placeholders.
    # The loop continues until the string no longer changes.
    expanded = s
    previous = None
    max_iterations = 10  # Safety break for infinite recursion
    for _i in range(max_iterations):
        if expanded == previous:
            break  # Expansion is complete
        previous = expanded
        expanded = expanded.format_map(_SafeFormatter(context))
    else:
        logger.warning(
            f"Template expansion reached max iterations ({max_iterations}). Possible recursive definition in '{s}'."
        )

    logger.debug(f"Expanded '{s}' into '{expanded}'")

    # throw an error if any remaining unexpanded variables remain unexpanded
    unexpanded_vars = re.findall(r"\{([^{}]+)\}", expanded)

    # Remove duplicates
    unexpanded_vars = list(dict.fromkeys(unexpanded_vars))
    if unexpanded_vars:
        raise KeyError("Missing context variable(s): " + ", ".join(unexpanded_vars))

    return expanded


def expand_context_list(strings: list[str] | list[Path], context: dict) -> list[str]:
    """Expand a list of strings with context variables."""
    return [expand_context_unsafe(str(s), context) for s in strings]


def expand_context_dict(d: dict[str, str], context: dict) -> dict[str, Any]:
    """Expand all values in a dictionary with context variables."""
    return {k: expand_context_typed(v, context) for k, v in d.items()}


def expand_context_typed(s: str, context: dict) -> Any:
    """Expand a string with context variables and return it as type T."""
    expanded = expand_context_unsafe(s, context)

    # if expanded can be successfully parsed as a float, convert to a float (ignore T for this purpose)
    # FIXME: really we should add a type option to parameters in toml.  And use that type information once we know
    # the name of the symbol we found.  But for now we do this hack to make floats work.
    try:
        return float(expanded)  # type: ignore[return-value]
    except ValueError:
        pass

    return expanded  # type: ignore[return-value]


def expand_context_unsafe(s: str, context: dict) -> str:
    """Expand a string with Python expressions in curly braces using RestrictedPython.

    Context variables are directly available in expressions without a prefix.

    Supports expressions like:
    - "foo {1 + 2}" -> "foo 3"
    - "bar {name}" -> "bar <value of context['name']>"
    - "path {instrument}/{date}/file.fits" -> "path MyScope/2025-01-01/file.fits"
    - "sum {x + y}" -> "sum <value of context['x'] + context['y']>"

    Args:
        s: String with Python expressions in curly braces
        context: Dictionary of variables available directly in expressions

    Returns:
        String with all expressions evaluated and substituted

    Raises:
        ValueError: If any expression cannot be evaluated (syntax errors, missing variables, etc.)

    Note: Uses RestrictedPython for safety, but still has security implications.
    This is a more powerful but less safe alternative to expand_context().
    """
    # Find all expressions in curly braces
    pattern = r"\{([^{}]+)\}"

    def eval_expression(match):
        """Evaluate a single expression and return its string representation."""
        expr = match.group(1).strip()

        try:
            # Compile the expression with RestrictedPython
            byte_code = RestrictedPython.compile_restricted(
                expr, filename="<template expression>", mode="eval"
            )

            # Evaluate with safe globals and the context
            result = eval(byte_code, make_safe_globals(context), None)
            return str(result)

        except Exception as e:
            raise ValueError(f"Failed to evaluate '{expr}' in context") from e

    # Iteratively expand the string to handle nested placeholders.
    # The loop continues until the string no longer changes.
    expanded = s
    previous = None
    max_iterations = 10  # Safety break for infinite recursion
    for _i in range(max_iterations):
        if expanded == previous:
            break  # Expansion is complete
        previous = expanded
        expanded = re.sub(pattern, eval_expression, expanded)
    else:
        logger.warning(
            f"Template expansion reached max iterations ({max_iterations}). Possible recursive definition in '{s}'."
        )

    logger.debug(f"Unsafe expanded '{s}' into '{expanded}'")

    return expanded


class MyPrinter(RestrictedPython.PrintCollector):
    def write(self, text):
        logger.info(f"Script print: {text}")
        super().write(text)


def my__import__(
    name: str,
    globals: Mapping[str, object] | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = (),
    level: int = 0,
) -> types.ModuleType:
    """A custom __import__ function for RestrictedPython that allows safe imports.

    Note: This is currently very unsafe as it allows all imports.
    A more restrictive policy should be implemented here.
    """
    if name == "sirilpy":
        name = "starbash.sim_siril"
        return importlib.import_module(name)
        # Use our sim version instead, we use import_module because we want the inner sim_siril module not just the package

    return __import__(name, globals, locals, fromlist, level)


def make_safe_globals(extra_globals: dict = {}) -> dict:
    """Generate a set of RestrictedPython globals for AstoGlue exec/eval usage"""
    # Define the global and local namespaces for the restricted execution.
    # FIXME - this is still unsafe, policies need to be added to limit import/getattr etc...
    # see https://restrictedpython.readthedocs.io/en/latest/usage/policy.html#implementing-a-policy

    builtins = RestrictedPython.safe_builtins.copy()

    def write_test(obj):
        """``_write_`` is a guard function taking a single argument.  If the
        object passed to it may be written to, it should be returned,
        otherwise the guard function should raise an exception.  ``_write_``
        is typically called on an object before a ``setattr`` operation."""
        return obj

    def getitem_glue(baseobj, index):
        return baseobj[index]

    def getattr_glue(obj, name, default=None):
        """Safe attribute access policy that allows special methods like __init__."""
        # Allow access to common special methods needed for basic Python functionality
        allowed_special = {
            "__init__",
            "__class__",
            "__dict__",
            "__doc__",
            "__name__",
            "__module__",
            "__repr__",
            "__str__",
        }

        # If it's an allowed special method, allow it
        if name in allowed_special:
            return getattr(obj, name, default)

        # If it starts with underscore, block it (security)
        if name.startswith("_"):
            raise AttributeError(f'"{name}" is an invalid attribute name because it starts with "_".')

        # Otherwise allow normal attribute access
        return getattr(obj, name, default)

    extras = {
        "__import__": my__import__,  # FIXME very unsafe
        "_getitem_": getitem_glue,  # why isn't the default guarded getitem found?
        "_getiter_": iter,  # Allows for loops and other iterations.
        "_unpack_sequence_": RestrictedPython.Guards.guarded_unpack_sequence,  # Required for tuple unpacking  # pyright: ignore[reportAttributeAccessIssue]
        "_write_": write_test,
        "_print_": MyPrinter,
        "_getattr_": getattr_glue,  # Custom attribute access policy
        # Add common built-in types
        "list": list,
        "dict": dict,
        "str": str,
        "int": int,
        "object": object,
        "all": all,
        # Add common built-in functions for math operations
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,  # Note: abs is already in safe_builtins, but explicit is better
        "round": round,  # Note: round is already in safe_builtins
    }
    builtins.update(extras)

    # Add RestrictedPython's utility_builtins for safe access to math, random, string modules
    from RestrictedPython.Utilities import utility_builtins
    builtins.update(utility_builtins)

    execution_globals = {
        # Required for RestrictedPython
        "__builtins__": builtins,
        "__name__": "__starbash_script__", # Loaded scripts can check for this name to know we are in starbash
        "__metaclass__": type,
        # Extra globals auto imported into the scripts context
        "logger": logging.getLogger("script"),  # Allow logging within the script,

        # Used by siril scripts without importing
        "staticmethod": staticmethod,
    }
    execution_globals.update(extra_globals)
    return execution_globals


def strip_comments(text: str) -> str:
    """Removes comments from a string.

    This function removes both full-line comments (lines starting with '#')
    and inline comments (text after '#' on a line).
    """
    lines = []
    for line in text.splitlines():
        lines.append(line.split("#", 1)[0].rstrip())
    return "\n".join(lines)
