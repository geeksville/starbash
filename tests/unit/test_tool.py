"""Tests for the tool module."""

import configparser
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from starbash import events
from starbash.tool import (
    GraxpertBuiltinTool,
    GraxpertExternalTool,
    PythonScriptError,
    PythonTool,
    RCAstroTool,
    SirilTool,
    Tool,
    ToolError,
    ToolSeverity,
    ToolStatus,
    _SafeFormatter,
    expand_context,
    expand_context_unsafe,
    make_safe_globals,
    set_tool_ignored,
    siril,
    strip_comments,
    tool_run,
    tools,
)
from starbash.tool.base import ExternalTool, quote_executable, tool_run_streaming
from starbash.tool.rcastro import parse_json_line
from starbash.tool.siril import link_or_copy_to_dir


class TestSafeFormatter:
    """Tests for _SafeFormatter class."""

    def test_missing_key_returns_placeholder(self):
        """Test that missing keys return the placeholder unchanged."""
        formatter = _SafeFormatter({"name": "Alice"})
        assert formatter["name"] == "Alice"
        assert formatter["missing"] == "{missing}"

    def test_existing_key_returns_value(self):
        """Test that existing keys return their values."""
        formatter = _SafeFormatter({"foo": "bar", "num": 42})
        assert formatter["foo"] == "bar"
        assert formatter["num"] == 42


class TestExpandContext:
    """Tests for expand_context function."""

    def test_simple_expansion(self):
        """Test simple variable expansion."""
        result = expand_context("Hello {name}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_variables(self):
        """Test expansion with multiple variables."""
        context = {"first": "John", "last": "Doe"}
        result = expand_context("{first} {last}", context)
        assert result == "John Doe"

    def test_nested_expansion(self):
        """Test nested variable expansion."""
        context = {"inner": "value", "outer": "{inner}"}
        result = expand_context("{outer}", context)
        assert result == "value"

    def test_missing_variable_raises_error(self):
        """Test that missing variables raise KeyError."""
        with pytest.raises(KeyError) as exc_info:
            expand_context("Hello {missing}!", {"name": "World"})
        assert "missing" in str(exc_info.value)

    def test_multiple_missing_variables(self):
        """Test error message includes all missing variables."""
        with pytest.raises(KeyError) as exc_info:
            expand_context("{var1} and {var2}", {})
        error_msg = str(exc_info.value)
        assert "var1" in error_msg
        assert "var2" in error_msg

    def test_empty_context(self):
        """Test expansion with no placeholders."""
        result = expand_context("No placeholders here", {})
        assert result == "No placeholders here"

    def test_max_iterations_warning(self, caplog):
        """Test that recursive definitions trigger max iterations warning."""
        import logging

        caplog.set_level(logging.WARNING)

        # Create a circular reference
        context = {"a": "{b}", "b": "{a}"}
        # Should reach max iterations and log warning, then raise KeyError for unexpanded vars
        with pytest.raises(KeyError) as exc_info:
            expand_context("{a}", context)

        # Check warning was logged
        assert "reached max iterations" in caplog.text
        assert "a" in str(exc_info.value)

    def test_no_expansion_needed(self):
        """Test string with no variables."""
        result = expand_context("plain text", {"var": "value"})
        assert result == "plain text"

    def test_escaped_braces_remain(self):
        """Test that context variables work with adjacent text."""
        result = expand_context("test_{var}_end", {"var": "middle"})
        assert result == "test_middle_end"


class TestExpandContextUnsafe:
    """Tests for expand_context_unsafe function using RestrictedPython."""

    def test_simple_arithmetic(self):
        """Test simple arithmetic expression."""
        result = expand_context_unsafe("result: {1 + 2}", {})
        assert result == "result: 3"

    def test_string_concatenation(self):
        """Test string concatenation in expression."""
        result = expand_context_unsafe("name: {'Hello' + ' ' + 'World'}", {})
        assert result == "name: Hello World"

    def test_direct_variable_access(self):
        """Test accessing context variables directly (without prefix)."""
        context = {"name": "Alice", "age": 30}
        result = expand_context_unsafe("User: {name}", context)
        assert result == "User: Alice"

    def test_path_building(self):
        """Test building filesystem paths (real use case)."""
        context = {"instrument": "MyScope", "date": "2025-01-01", "imagetyp": "BIAS"}
        result = expand_context_unsafe("{instrument}/{date}/{imagetyp}/output.fits", context)
        assert result == "MyScope/2025-01-01/BIAS/output.fits"

    def test_arithmetic_with_context(self):
        """Test arithmetic using context values."""
        context = {"x": 5, "y": 3}
        result = expand_context_unsafe("Sum: {x + y}", context)
        assert result == "Sum: 8"

    def test_string_formatting(self):
        """Test string formatting expressions."""
        context = {"value": 42}
        result = expand_context_unsafe("Value is {value}", context)
        assert result == "Value is 42"

    def test_no_expressions(self):
        """Test string with no expressions."""
        result = expand_context_unsafe("plain text", {})
        assert result == "plain text"

    def test_invalid_expression_raises_error(self):
        """Test that invalid expressions raise ValueError."""
        # Invalid syntax should raise ValueError
        with pytest.raises(ValueError, match="Failed to evaluate"):
            expand_context_unsafe("bad: {this is not valid}", {})

    def test_missing_variable_raises_error(self):
        """Test that missing variables raise ValueError."""
        with pytest.raises(ValueError, match="Failed to evaluate.*missing"):
            expand_context_unsafe("value: {missing}", {})


class TestMakeSafeGlobals:
    """Tests for make_safe_globals function."""

    def test_returns_dict(self):
        """Test that function returns a dictionary."""
        result = make_safe_globals()
        assert isinstance(result, dict)

    def test_includes_builtins(self):
        """Test that safe globals include __builtins__."""
        result = make_safe_globals()
        assert "__builtins__" in result
        assert isinstance(result["__builtins__"], dict)

    def test_includes_context(self):
        """Test that context items are merged into execution globals."""
        test_context = {"key": "value", "another_key": 42}
        result = make_safe_globals(test_context)
        # Context items should be merged directly into execution_globals
        assert result["key"] == "value"
        assert result["another_key"] == 42

    def test_includes_logger(self):
        """Test that logger is available."""
        result = make_safe_globals()
        assert "logger" in result

    def test_includes_common_types(self):
        """Test that common built-in types are available."""
        result = make_safe_globals()
        builtins = result["__builtins__"]
        assert "list" in builtins
        assert "dict" in builtins
        assert "str" in builtins
        assert "int" in builtins
        assert "all" in builtins

    def test_includes_required_guards(self):
        """Test that RestrictedPython guard functions are present."""
        result = make_safe_globals()
        builtins = result["__builtins__"]
        assert "_getitem_" in builtins
        assert "_getiter_" in builtins
        assert "_write_" in builtins

    def test_empty_context_by_default(self):
        """Test that execution_globals has base keys without extra context."""
        result = make_safe_globals()
        # Should have base keys like __builtins__, logger, etc.
        assert "__builtins__" in result
        assert "logger" in result
        # But no extra context variables should be added
        assert "key" not in result  # example context key should not be present

    def test_write_guard_function(self):
        """Test that _write_ guard function works."""
        result = make_safe_globals()
        write_func = result["__builtins__"]["_write_"]
        # write_test should just return the object passed to it
        test_obj = {"key": "value"}
        assert write_func(test_obj) == test_obj

    def test_includes_common_math_functions(self):
        """Test that common math functions like min, max, sum are available."""
        result = make_safe_globals()
        builtins = result["__builtins__"]
        assert "min" in builtins
        assert "max" in builtins
        assert "sum" in builtins
        assert "abs" in builtins
        assert "round" in builtins
        # Verify they actually work
        assert builtins["min"](1, 2, 3) == 1
        assert builtins["max"](1, 2, 3) == 3
        assert builtins["sum"]([1, 2, 3]) == 6

    def test_includes_utility_builtins(self):
        """Test that RestrictedPython utility_builtins are available (math, random, string modules)."""
        result = make_safe_globals()
        builtins = result["__builtins__"]
        # Check for utility_builtins items
        assert "math" in builtins
        assert "random" in builtins
        assert "string" in builtins
        assert "set" in builtins
        assert "frozenset" in builtins
        # Verify math module works
        import math as stdlib_math

        assert builtins["math"].sqrt(16) == stdlib_math.sqrt(16)
        assert builtins["math"].pi == stdlib_math.pi


class TestStripComments:
    """Tests for strip_comments function."""

    def test_removes_full_line_comment(self):
        """Test removal of full-line comments."""
        result = strip_comments("# This is a comment\ncode")
        assert result == "\ncode"

    def test_removes_inline_comment(self):
        """Test removal of inline comments."""
        result = strip_comments("code # inline comment")
        assert result == "code"

    def test_multiple_lines_with_comments(self):
        """Test comment removal across multiple lines."""
        text = "line1\n# comment\nline2 # inline\nline3"
        result = strip_comments(text)
        assert result == "line1\n\nline2\nline3"

    def test_no_comments(self):
        """Test text with no comments remains unchanged."""
        text = "no comments here"
        result = strip_comments(text)
        assert result == text

    def test_empty_string(self):
        """Test empty string handling."""
        result = strip_comments("")
        assert result == ""

    def test_hash_in_string_context(self):
        """Test that # in actual code is removed (simple implementation)."""
        # Note: This is a simple implementation that doesn't handle string contexts
        result = strip_comments('print("test") # comment')
        assert result == 'print("test")'


class TestToolBaseClass:
    """Tests for Tool base class."""

    def test_tool_has_name(self):
        """Test that Tool stores its name."""
        tool = Tool("test_tool")
        assert tool.name == "test_tool"

    def test_tool_default_script_file_is_none(self):
        """Test default script file is None."""
        tool = Tool("test")
        assert tool.default_script_file is None

    def test_run_not_implemented(self):
        """Test that _run() raises NotImplementedError."""
        tool = Tool("test")
        with pytest.raises(NotImplementedError):
            tool.run("commands", {}, tempfile.gettempdir())

    def test_run_creates_temp_directory(self):
        """Test that run creates and cleans up temp directory."""

        class TestTool(Tool):
            def __init__(self):
                super().__init__("test")
                self.received_cwd = None
                self.received_context_copy = None

            def _run(
                self,
                cwd: str,
                commands: str | list[str],
                context: dict = {},
                log_out: Any = None,
                **kwargs: Any,
            ) -> None:
                self.received_cwd = cwd
                # Make a copy of context to verify temp_dir was present during execution
                self.received_context_copy = dict(context)
                # Verify temp directory exists during execution
                assert os.path.isdir(cwd)
                assert cwd.startswith(tempfile.gettempdir())
                # Verify temp_dir is in context during execution
                assert "temp_dir" in context
                assert context["temp_dir"] == cwd

        tool = TestTool()
        context = {"key": "value"}
        tool.run("test commands", context)

        # Verify temp_dir was present during execution
        assert tool.received_context_copy is not None
        assert "temp_dir" in tool.received_context_copy
        # Verify temp_dir was removed after execution
        assert "temp_dir" not in context
        # Verify temp directory was cleaned up
        assert tool.received_cwd is not None
        assert not os.path.exists(tool.received_cwd)


class TestPythonTool:
    """Tests for PythonTool class."""

    def test_python_tool_name(self):
        """Test PythonTool has correct name."""
        tool = PythonTool()
        assert tool.name == "python"

    def test_python_tool_default_script_file(self):
        """Test PythonTool has correct default script file."""
        tool = PythonTool()
        assert tool.default_script_file == "starbash.py"

    def test_python_tool_executes_simple_code(self):
        """Test PythonTool can execute simple Python code."""
        tool = PythonTool()
        context = {"result": []}

        # Use context to capture results since we can't easily capture stdout
        code = "context['result'].append(42)"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(code, context, temp_dir)
            assert context["result"] == [42]

    def test_python_tool_has_access_to_context(self):
        """Test that Python scripts can access context variables."""
        tool = PythonTool()
        context = {"input": 10, "output": []}

        code = "context['output'].append(context['input'] * 2)"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(code, context, temp_dir)
            assert context["output"] == [20]

    def test_python_tool_syntax_error_raises(self):
        """Test that syntax errors are raised properly."""
        tool = PythonTool()

        code = "if True"  # Invalid syntax

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(PythonScriptError) as exc_info:
                tool.run(code, {}, temp_dir)
            # RestrictedPython provides detailed syntax error messages
            assert "Script syntax error" in str(exc_info.value)

    def test_python_tool_runtime_error_raises(self):
        """Test that runtime errors are wrapped in PythonScriptError."""
        tool = PythonTool()

        code = "raise ValueError('test error')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(PythonScriptError) as exc_info:
                tool.run(code, {}, temp_dir)
            # The error is wrapped, so we get the generic message
            assert "Python script error" in str(exc_info.value)

    def test_python_tool_hides_unused_print_collector_warning(self):
        """Recipe compilation does not expose RestrictedPython internals to users."""
        import warnings

        tool = PythonTool()
        with tempfile.TemporaryDirectory() as temp_dir:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                tool.run("print('hello')", {}, temp_dir)

        assert not any(
            "never reads 'printed' variable" in str(warning.message) for warning in caught
        )

    def test_python_tool_changes_directory(self):
        """Test that Python tool changes to the working directory."""
        tool = PythonTool()
        original_cwd = os.getcwd()
        context = {"cwd_during_run": []}

        code = "import os; context['cwd_during_run'].append(os.getcwd())"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(code, context, temp_dir)
            # Verify cwd was changed during execution. Use realpath to
            # resolve macOS /private vs /var symlink differences.
            assert os.path.realpath(context["cwd_during_run"][0]) == os.path.realpath(temp_dir)
            # Verify cwd was restored after execution
            assert os.getcwd() == original_cwd

    def test_python_tool_restores_directory_on_error(self):
        """Test that directory is restored even on error."""
        from starbash.tool.python import PythonScriptError

        tool = PythonTool()
        original_cwd = os.getcwd()

        code = "raise RuntimeError('test')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(PythonScriptError):  # Exceptions are wrapped in PythonScriptError
                tool.run(code, {}, temp_dir)
            # Verify cwd was restored after error
            assert os.getcwd() == original_cwd


class TestSirilTool:
    """Tests for SirilTool class."""

    def test_siril_tool_name(self):
        """Test SirilTool has correct name."""
        tool = SirilTool()
        assert tool.name == "Siril"

    def test_siril_tool_expands_context(self):
        """Test that SirilTool expands context variables in commands."""
        tool = SirilTool()
        # We can't easily test the actual siril execution without mocking subprocess,
        # but we can verify the tool is instantiated correctly
        assert tool.name == "Siril"

    def test_siril_tool_uses_windows_default_path(self, monkeypatch):
        """Windows probes the default location used by the Siril installer."""
        monkeypatch.setattr(siril.sys, "platform", "win32")

        tool = SirilTool()

        assert tool.commands[-1] == r"C:\Program Files\Siril\bin\siril.exe"


def test_external_tool_uses_an_absolute_executable_path(tmp_path):
    """An absolute command candidate works without needing to be on ``PATH``."""
    executable = tmp_path / ("tool.exe" if os.name == "nt" else "tool")
    executable.write_text("#!/bin/sh\n")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    tool = ExternalTool("Test tool", [str(executable)], "https://example.test")

    assert tool.executable_path == str(executable)


class TestLinkOrCopyToDir:
    """The Siril input collector reports on the bus instead of drawing a bar.

    It runs for every Siril stage, *inside* a processing run, and a
    ``rich.progress.track()`` there builds its own ``Console`` on stdout -- a
    second bar painted over the CLI's one live display, and stdout output from a
    GUI worker.  The CLI's bar has a "Collecting inputs" phase for these counts.
    """

    def test_it_reports_its_counts_and_completion(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        # Spans the 25-frame reporting interval, so the final count is the last
        # iteration rather than a multiple of 25.
        frames = 26
        inputs: list[Path] = []
        for index in range(1, frames + 1):
            path = source / f"light_{index:04d}.fits"
            path.touch()
            inputs.append(path)
        dest = tmp_path / "work" / "stack"
        dest.mkdir(parents=True)

        captured: list[events.Event] = []
        unsubscribe = events.subscribe(captured.append)
        try:
            link_or_copy_to_dir(inputs, str(dest))
        finally:
            unsubscribe()

        assert [(event.kind, event.data) for event in captured] == [
            (events.EVENT_MERGE_PROGRESS, {"name": "stack", "done": 0, "total": frames}),
            (events.EVENT_MERGE_PROGRESS, {"name": "stack", "done": 25, "total": frames}),
            (events.EVENT_MERGE_PROGRESS, {"name": "stack", "done": frames, "total": frames}),
            (events.EVENT_MERGE_FINISHED, {"name": "stack", "files": frames}),
        ]
        # The reported counts have to describe work that actually happened.
        assert sorted(path.name for path in dest.iterdir()) == sorted(path.name for path in inputs)

    def test_a_second_run_keeps_the_input_it_already_has(self, tmp_path):
        """An input already in place is left alone -- and is still reported.

        A re-run of a Siril stage meets its own links, so the collector skips them;
        the counts it reports must cover those frames too, or the phase would stop
        short of its total.
        """
        source = tmp_path / "source"
        source.mkdir()
        frame = source / "light_0001.fits"
        frame.touch()
        dest = tmp_path / "work" / "stack"
        dest.mkdir(parents=True)
        already = dest / "light_0001.fits"
        already.write_text("from an earlier stage")

        captured: list[events.Event] = []
        unsubscribe = events.subscribe(captured.append)
        try:
            link_or_copy_to_dir([frame], str(dest))
        finally:
            unsubscribe()

        assert [event.data for event in captured if event.kind == events.EVENT_MERGE_PROGRESS] == [
            {"name": "stack", "done": 0, "total": 1},
            {"name": "stack", "done": 1, "total": 1},
        ]
        assert captured[-1].kind == events.EVENT_MERGE_FINISHED
        assert already.read_text() == "from an earlier stage"


class TestToolsDict:
    """Tests for tools dictionary."""

    def test_tools_dict_exists(self):
        """Test that tools dict is defined."""
        assert tools is not None
        assert isinstance(tools, dict)

    def test_tools_dict_contains_all_tools(self):
        """Test that all tool instances are registered."""
        assert "siril" in tools
        assert "graxpert" in tools
        assert "python" in tools

    def test_tools_dict_values_are_tool_instances(self):
        """Test that dict values are Tool instances."""
        assert isinstance(tools["siril"], SirilTool)
        # assert isinstance(tools["graxpert"], GraxpertBuiltinTool)
        assert isinstance(tools["python"], PythonTool)

    def test_tools_dict_keys_match_names(self):
        """Test that dict keys are lowercase versions of tool names."""
        for key, tool in tools.items():
            assert key == tool.name.lower()


class _FakeTool(Tool):
    """A tool whose availability a test controls (the real probes look at disk)."""

    def __init__(self, name: str, severity: ToolSeverity, available: bool) -> None:
        super().__init__(name)
        self.severity = severity
        self.install_url = "https://example.test/install"
        self._available = available

    @property
    def is_available(self) -> bool:
        """Whether this fake tool is installed."""
        return self._available

    def missing_message(self) -> str:
        """Explain why this fake tool is unavailable."""
        return f"The {self.name} executable was not found."


class TestToolSeverity:
    """Tests for severity-aware status, ignores and preflight logging."""

    @pytest.fixture(autouse=True)
    def _clean_preferences(self, monkeypatch):
        """Tool preferences are process-wide, so give each test a clean copy."""
        monkeypatch.setattr(Tool, "Preferences", {})

    def test_severity_is_ordered_and_labelled(self):
        """The enum orders optional < recommended < required, for comparisons."""
        assert ToolSeverity.OPTIONAL < ToolSeverity.RECOMMENDED < ToolSeverity.REQUIRED
        assert ToolSeverity.REQUIRED.label == "required"
        assert ToolSeverity.RECOMMENDED.label == "recommended"
        assert ToolSeverity.OPTIONAL.label == "optional"

    def test_registry_tags_each_tool_with_its_severity(self):
        """Siril is required, StarNet recommended, the rest optional."""
        assert tools["siril"].severity is ToolSeverity.REQUIRED
        assert tools["starnet"].severity is ToolSeverity.RECOMMENDED
        assert tools["graxpert"].severity is ToolSeverity.OPTIONAL
        assert tools["rc-astro"].severity is ToolSeverity.OPTIONAL

    def test_status_reports_a_missing_tool(self):
        """A missing tool's status carries its key, severity, link and explanation."""
        tool = _FakeTool("Fake", ToolSeverity.RECOMMENDED, available=False)
        status = tool.status()

        assert (status.name, status.key) == ("Fake", "fake")
        assert status.severity is ToolSeverity.RECOMMENDED
        assert status.available is False
        assert status.needs_attention is True
        assert status.install_url == "https://example.test/install"
        assert status.detail == "The Fake executable was not found."
        assert status.summary == "The Fake executable was not found."

    def test_an_installed_tool_never_needs_attention(self):
        """Nothing to report (and no detail) once the tool is found."""
        tool = _FakeTool("Fake", ToolSeverity.REQUIRED, available=True)
        status = tool.status()

        assert status.available is True
        assert status.needs_attention is False
        assert status.detail is None
        assert status.summary == ""

    def test_ignoring_a_tool_silences_its_status(self):
        """The ``ignored`` preference is what the GUI's Ignore button persists."""
        tool = _FakeTool("Fake", ToolSeverity.RECOMMENDED, available=False)
        assert tool.is_ignored is False

        set_tool_ignored("fake")

        assert tool.is_ignored is True
        assert tool.status().ignored is True
        assert tool.status().needs_attention is False

    def test_only_non_required_warnings_can_be_ignored(self):
        """A required tool keeps warning: you cannot dismiss Siril away."""
        required = ToolStatus("Siril", "siril", ToolSeverity.REQUIRED, available=False)
        recommended = ToolStatus("StarNet", "starnet", ToolSeverity.RECOMMENDED, available=False)

        assert required.can_be_ignored is False
        assert recommended.can_be_ignored is True

    def test_missing_tool_statuses_sorts_by_severity_and_skips_ignored(self, monkeypatch):
        """Most important first, and an ignored tool is left out by default."""
        from starbash import tool as tool_module

        statuses = [
            ToolStatus("Python", "python", ToolSeverity.OPTIONAL, available=True),
            ToolStatus("rc-astro", "rc-astro", ToolSeverity.OPTIONAL, available=False),
            ToolStatus(
                "StarNet",
                "starnet",
                ToolSeverity.RECOMMENDED,
                available=False,
                ignored=True,
            ),
            ToolStatus("Siril", "siril", ToolSeverity.REQUIRED, available=False),
        ]
        monkeypatch.setattr(tool_module, "tool_statuses", lambda: statuses)

        assert [s.key for s in tool_module.missing_tool_statuses()] == ["siril", "rc-astro"]
        # ``include_ignored`` is the diagnostics view: everything missing, as probed.
        assert [s.key for s in tool_module.missing_tool_statuses(include_ignored=True)] == [
            "rc-astro",
            "starnet",
            "siril",
        ]

    def test_preflight_reports_a_missing_tool_by_severity(self, caplog):
        """Required logs an error, recommended a warning, optional only debug."""
        cases = [
            (ToolSeverity.REQUIRED, logging.ERROR),
            (ToolSeverity.RECOMMENDED, logging.WARNING),
            (ToolSeverity.OPTIONAL, logging.DEBUG),
        ]
        for severity, expected in cases:
            tool = _FakeTool("Fake", severity, available=False)
            with caplog.at_level(logging.DEBUG):
                tool.preflight()
            assert caplog.records, f"a missing {severity.label} tool must be reported"
            assert caplog.records[-1].levelno == expected

    def test_preflight_is_silent_for_installed_or_ignored_tools(self, caplog):
        """Nothing is logged when there is nothing to do about it."""
        installed = _FakeTool("Installed", ToolSeverity.REQUIRED, available=True)
        with caplog.at_level(logging.DEBUG):
            installed.preflight()
        assert caplog.records == []

        ignored = _FakeTool("Ignored", ToolSeverity.REQUIRED, available=False)
        set_tool_ignored("ignored")
        with caplog.at_level(logging.DEBUG):
            ignored.preflight()
        assert caplog.records == []


class TestToolRun:
    """Tests for tool_run function."""

    def test_quote_executable_quotes_windows_paths_with_spaces(self, monkeypatch):
        """Windows command shells need quoted executable paths with spaces."""
        from starbash.tool import base

        monkeypatch.setattr(base.sys, "platform", "win32")

        assert quote_executable(r"C:\Program Files\Siril\bin\siril.exe") == (
            r'"C:\Program Files\Siril\bin\siril.exe"'
        )

    def test_tool_run_success(self):
        """Test successful tool execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Use a real command - echo should work on all platforms
            tool_run("echo hello", temp_dir)
            # If we get here without exception, the command succeeded

    @pytest.mark.skipif(
        os.name == "nt", reason="Shell quoting with spaces not supported on Windows cmd.exe"
    )
    def test_tool_run_with_spaces_in_command_path(self):
        """Test that tool_run handles command paths with spaces correctly."""
        import sys

        with tempfile.TemporaryDirectory() as temp_dir:
            # Test 1: Full path to Python executable
            python_path = sys.executable

            # This should work - full path with no spaces
            tool_run(f'{python_path} -c "pass"', temp_dir)

            # Test 2: Create a temp directory with spaces in the name
            spaces_dir_name = "temp dir with spaces"
            spaces_dir = os.path.join(temp_dir, spaces_dir_name)
            os.makedirs(spaces_dir, exist_ok=True)

            # Create a symlink to python in the directory with spaces
            symlink_path = os.path.join(spaces_dir, "python")
            try:
                os.symlink(python_path, symlink_path)
            except OSError:
                # Symlink creation might fail on some systems (e.g., Windows without privileges)
                pytest.skip("Cannot create symlinks on this system")

            # Test with unquoted path - this will fail because shell splits on spaces
            with pytest.raises(ToolError):
                tool_run(f'{symlink_path} -c "pass"', temp_dir)

            # The shared tool helper quotes paths correctly before passing them
            # to a shell-based external tool runner.
            tool_run(f'{quote_executable(symlink_path)} -c "pass"', temp_dir)

    @pytest.mark.skipif(os.name == "nt", reason="Shell redirection syntax not supported on Windows")
    def test_tool_run_with_stderr_warning(self, caplog):
        """Test that stderr output is logged as warning."""
        import logging

        caplog.set_level(logging.WARNING)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Use echo with stderr redirection - >&2 redirects to stderr
            tool_run("cat >&2", cwd=temp_dir, commands="warning message")

            # Check that stderr was logged as warning
            assert "warning message" in caplog.text
            assert "tool-warnings" in caplog.text

    def test_tool_run_failure_raises_error(self):
        """Test that non-zero return code raises ToolError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 'false' command always exits with code 1
            with pytest.raises(ToolError, match="failed with exit code 1"):
                tool_run("false", temp_dir)

    def test_tool_run_timeout(self):
        """Test that timeout works correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 'sleep 5' will take 5 seconds, but we timeout after 1 second
            with pytest.raises(RuntimeError, match="Tool timed out after 1 seconds"):
                tool_run("sleep 5", temp_dir, timeout=1)

    @pytest.mark.skipif(os.name == "nt", reason="Shell redirection syntax not supported on Windows")
    def test_tool_run_failure_logs_output(self, caplog):
        """Test that failure logs both stdout and stderr."""
        import logging

        caplog.set_level(logging.WARNING)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Command that outputs to both stdout and stderr then fails
            # Use sh -c to ensure proper output handling
            with pytest.raises(ToolError):
                tool_run(
                    "sh -c 'echo error output; echo error message >&2; exit 1'",
                    temp_dir,
                )

            # stderr is logged as warning
            assert "error message" in caplog.text
            assert "tool-warnings" in caplog.text

    def test_tool_run_logs_stdout_on_success(self, caplog):
        """Test that stdout is logged on successful run."""
        import logging

        caplog.set_level(logging.DEBUG, logger="starbash.tool.base")

        with tempfile.TemporaryDirectory() as temp_dir:
            tool_run("echo successful output", temp_dir)

            # Check debug logs
            assert "Tool command successful" in caplog.text
            assert "successful output" in caplog.text


class TestSirilToolRun:
    """Tests for SirilTool.run method."""

    def test_siril_tool_run_with_empty_script(self):
        """Test that SirilTool.run can execute Siril with empty script."""

        # We now install Siril on all of our CI runners, so make this test mandatory.
        # Skip test if Siril is not available
        # siril_commands = ["siril-cli", "siril", "org.siril.Siril"]
        # siril_available = any(shutil.which(cmd) for cmd in siril_commands)
        # if not siril_available:
        #    pytest.skip("Siril not available on this system")

        tool = SirilTool()
        tool.timeout = 30.0  # 30 second timeout for test

        with tempfile.TemporaryDirectory() as temp_dir:
            # Just run with empty script to verify Siril executes
            tool.run("", {}, temp_dir)


class TestGraxpertToolRun:
    """Tests for GraxpertTool.run method."""

    @pytest.mark.slow
    def test_graxpert_tool_run_with_help(self):
        """Test that GraxpertTool.run can execute GraXpert."""

        # Skip test if GraXpert is not available
        if not shutil.which("graxpert"):
            pytest.skip("GraXpert not available on this system")

        tool = GraxpertExternalTool()
        tool.timeout = 10.0  # 10 second timeout for test

        with tempfile.TemporaryDirectory() as temp_dir:
            # Just run --help to verify GraXpert executes
            # Note: --help may exit with non-zero in some versions
            try:
                tool.run("--help", {}, temp_dir)
            except RuntimeError as e:
                # Allow --help to fail (argparse behavior varies)
                # Just verify the tool was found
                if "not found" in str(e).lower():
                    pytest.fail("GraXpert command not found")


class TestParseJsonLine:
    """Tests for rc-astro JSON line parsing."""

    def test_parses_progress_event(self):
        obj = parse_json_line('{"event":"progress","done":50.0,"eta":10.0}')
        assert obj is not None
        assert obj["event"] == "progress"
        assert obj["done"] == 50.0

    def test_parses_status_event(self):
        obj = parse_json_line('{"event":"status","phase":"saving","message":"Saving"}')
        assert obj is not None
        assert obj["message"] == "Saving"

    def test_blank_line_returns_none(self):
        assert parse_json_line("   ") is None

    def test_non_json_line_returns_none(self):
        assert parse_json_line("some diagnostic text") is None

    def test_non_object_json_returns_none(self):
        # Valid JSON, but not a dict
        assert parse_json_line("[1, 2, 3]") is None

    def test_sample_stream_progress_and_status(self):
        """Feed the design-doc sample lines and assert progress + status are captured."""
        sample = [
            '{"event":"info","topic":"version","cliVersion":"1.1.3","schemaVersion":4}',
            '{"event":"status","phase":"initializing","message":"Initializing"}',
            '{"event":"progress","done":0.6,"mpPerSec":0.1,"eta":237.1}',
            '{"event":"progress","done":100.0,"mpPerSec":0.2,"eta":0.0}',
            '{"event":"status","phase":"complete","message":"Done","output":"foo.fits"}',
            "not a json line",
        ]
        parsed = [parse_json_line(line) for line in sample]
        # last (non-json) line ignored
        assert parsed[-1] is None
        progress = [p for p in parsed if p and p["event"] == "progress"]
        assert [p["done"] for p in progress] == [0.6, 100.0]
        statuses = [p["message"] for p in parsed if p and p["event"] == "status"]
        assert statuses == ["Initializing", "Done"]


class TestRCAstroTool:
    """Tests for RCAstroTool argument construction and execution."""

    def test_build_args_injects_json(self):
        tool = RCAstroTool()
        args = tool.build_args(["bxt", "in.fits", "--output", "out.fits"], {})
        assert args == ["--json", "bxt", "in.fits", "--output", "out.fits"]

    def test_build_args_does_not_duplicate_json(self):
        tool = RCAstroTool()
        args = tool.build_args(["--json", "bxt", "in.fits"], {})
        assert args.count("--json") == 1

    def test_build_args_expands_context(self):
        tool = RCAstroTool()
        args = tool.build_args(
            ["bxt", "{input}", "--sharpen-stars", "{strength}"],
            {"input": "in.fits", "strength": "0.5"},
        )
        assert args == ["--json", "bxt", "in.fits", "--sharpen-stars", "0.5"]

    def test_build_args_drops_unset_parameter_flag(self):
        """A --flag whose value comes from an unset (None) parameter is omitted."""

        class _Params:
            set_val: Any
            unset_val: Any

        params = _Params()
        params.set_val = "0.5"
        params.unset_val = None  # no default, no override

        tool = RCAstroTool()
        args = tool.build_args(
            [
                "nxt",
                "in.fits",
                "--denoise",
                "{parameters.set_val}",
                "--denoise-intensity",
                "{parameters.unset_val}",
            ],
            {"parameters": params},
        )
        assert args == ["--json", "nxt", "in.fits", "--denoise", "0.5"]

    def test_registered_in_tools(self):
        assert isinstance(tools.get("rc-astro"), RCAstroTool)

    def test_run_builds_expected_command(self, monkeypatch):
        """RCAstroTool.run should build the full rc-astro command and stream output."""
        captured: dict[str, str] = {}

        def fake_stream(cmd, cwd, on_line, timeout=None, log_out=None, stdout_mime=None):
            captured["cmd"] = cmd
            # Handler must tolerate progress, status and non-json lines
            on_line('{"event":"progress","done":100.0,"eta":0.0}')
            on_line('{"event":"status","phase":"complete","message":"Done"}')
            on_line("not json")

        monkeypatch.setattr("starbash.tool.rcastro.tool_run_streaming", fake_stream)
        monkeypatch.setattr(Tool, "Preferences", {"rc-astro": {"path": "/usr/bin/rc-astro"}})

        tool = RCAstroTool()
        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(
                [
                    "bxt",
                    "in.fits",
                    "--output",
                    "out.fits",
                    "--sharpen-stars",
                    "0.5",
                    "--sharpen-nonstellar",
                    "0.5",
                ],
                context={},
                cwd=temp_dir,
            )

        assert captured["cmd"] == (
            "/usr/bin/rc-astro --json bxt in.fits --output out.fits "
            "--sharpen-stars 0.5 --sharpen-nonstellar 0.5"
        )


class TestToolRunStreaming:
    """Tests for the streaming subprocess runner."""

    def test_streaming_collects_lines(self):
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            tool_run_streaming(
                """echo '{"event":"progress","done":50.0}'""",
                temp_dir,
                on_line=lines.append,
            )
        assert any("progress" in line for line in lines)

    def test_streaming_failure_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ToolError, match="failed with exit code 1"):
                tool_run_streaming("false", temp_dir, on_line=lambda line: None)

    def test_streaming_timeout(self):
        import sys

        # Use the current interpreter so this works on Windows (no bash) and Unix alike
        slow_cmd = f'"{sys.executable}" -c "import time; [print(i, flush=True) or time.sleep(0.2) for i in range(10)]"'
        # ignore_cleanup_errors: on Windows, TerminateProcess doesn't immediately release the cwd handle
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            with pytest.raises(RuntimeError, match="timed out"):
                tool_run_streaming(
                    slow_cmd,
                    temp_dir,
                    on_line=lambda line: None,
                    timeout=0.3,
                )


class TestBlurExterminatorRecipe:
    """Tests that the blur-exterminator recipe is wired correctly."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = (
            Path(__file__).parents[2] / "starbash-recipes" / "rc-astro" / "blur-exterminator.toml"
        )
        return tomlkit.parse(recipe.read_text())

    def test_parameters_have_defaults(self):
        doc = self._load_recipe()
        params = {p["name"]: p for s in doc["stages"] for p in s.get("parameters", [])}
        assert params["sharpen_stars"]["default"] == 0.5
        assert params["sharpen_nonstellar"]["default"] == 0.5

    def test_stage_uses_rc_astro_after_background(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        assert stage["tool"]["name"] == "rc-astro"
        assert stage["inputs"][0]["after"] == "background.*"

    def test_stage_sorts_after_background(self):
        from starbash.stages import sort_stages

        doc = self._load_recipe()
        blur = doc["stages"][0]
        background = {"name": "background", "inputs": [{"after": "stack_.*"}]}
        ordered = sort_stages([blur, background])
        names = [s.get("name") for s in ordered]
        assert names.index("background") < names.index("blur_exterminator")


class TestNoiseExterminatorRecipe:
    """Tests that the noise-exterminator recipe is wired correctly."""

    # Recipe parameters (per-stage scoped, so the redundant nxt_ prefix is dropped).
    EXPECTED_PARAMS = [
        "denoise",
        "denoise_intensity",
        "denoise_color",
        "denoise_hf",
        "denoise_lf",
        "denoise_intensity_hf",
        "denoise_intensity_lf",
        "denoise_color_hf",
        "denoise_color_lf",
        "frequency_scale",
        "iterations",
    ]

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = (
            Path(__file__).parents[2] / "starbash-recipes" / "rc-astro" / "noise-exterminator.toml"
        )
        return tomlkit.parse(recipe.read_text())

    def test_parameters_are_declared(self):
        doc = self._load_recipe()
        params = {p["name"]: p for s in doc["stages"] for p in s.get("parameters", [])}
        for name in self.EXPECTED_PARAMS:
            assert name in params, f"missing parameter {name}"

    def test_stage_uses_rc_astro_after_blur(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        assert stage["name"] == "noise_exterminator"
        assert stage["tool"]["name"] == "rc-astro"
        assert stage["inputs"][0]["after"] == "blur_exterminator"
        assert stage["outputs"][0]["auto"]["prefix"] == "nx_"

    def test_stage_sorts_after_blur(self):
        from starbash.stages import sort_stages

        doc = self._load_recipe()
        noise = doc["stages"][0]
        background = {"name": "background", "inputs": [{"after": "stack_.*"}]}
        blur = {"name": "blur_exterminator", "inputs": [{"after": "background.*"}]}
        ordered = sort_stages([noise, blur, background])
        names = [s.get("name") for s in ordered]
        assert names.index("background") < names.index("blur_exterminator")
        assert names.index("blur_exterminator") < names.index("noise_exterminator")


class TestStarnetRecipe:
    """Tests that the starnet recipe is wired correctly."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = Path(__file__).parents[2] / "starbash-recipes" / "common" / "starnet.toml"
        return tomlkit.parse(recipe.read_text())

    def test_parameters_have_defaults(self):
        doc = self._load_recipe()
        params = {p["name"]: p for s in doc["stages"] for p in s.get("parameters", [])}
        assert params["params"]["default"] == "-stretch"

    def test_stage_uses_siril_after_sho(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        assert stage["name"] == "starnet"
        assert stage["tool"]["name"] == "starnet"
        assert stage["inputs"][0]["after"] == "palette.*"
        assert stage["inputs"][0]["multiplex"] is True
        assert "starnet {parameters.params}" in stage["script"]

    def test_declares_starless_and_starmask_outputs(self):
        doc = self._load_recipe()
        outputs = doc["stages"][0]["outputs"]
        # Both outputs must live in a single block so the script can reference
        # output.full_paths[0] (starless) and output.full_paths[1] (starmask).
        assert len(outputs) == 1
        names = list(outputs[0]["name"])
        assert len(names) == 2
        assert names[0].startswith("starless_")
        assert names[1].startswith("starmask_")

    def test_stage_sorts_after_sho(self):
        from starbash.stages import sort_stages

        doc = self._load_recipe()
        starnet = doc["stages"][0]
        sho = {"name": "palette.sho", "inputs": [{"after": "noise_exterminator"}]}
        ordered = sort_stages([starnet, sho])
        names = [s.get("name") for s in ordered]
        assert names.index("palette.sho") < names.index("starnet")


class TestCropRecipe:
    """Tests that the generalized crop recipe is wired correctly."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = Path(__file__).parents[2] / "starbash-recipes" / "common" / "crop.toml"
        return tomlkit.parse(recipe.read_text())

    def test_stage_is_multiplexed_after_stack(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        input_def = stage["inputs"][0]

        assert stage["name"] == "crop"
        assert stage["tool"]["name"] == "python"
        assert input_def["after"] == "stack_.*"
        assert input_def["multiplex"] is True
        assert input_def["requires"][0]["value"] == 1
        assert 'context["input"][0]' in stage["script"]
        assert 'context["output"]' in stage["script"]

    def test_stage_parameters_and_output(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        params = {p["name"]: p for p in stage["parameters"]}

        assert "crop_percent" not in params
        assert params["crop_width"]["default"] == "80%"
        assert params["crop_height"]["default"] == "80%"
        assert params["rotate_deg"]["default"] == 0
        assert 'crop_width=context["parameters"].crop_width' in stage["script"]
        assert 'crop_height=context["parameters"].crop_height' in stage["script"]
        assert stage["outputs"][0]["auto"]["prefix"] == "crop_"

    def test_default_manifest_includes_crop_recipe(self):
        import tomlkit

        manifest: Any = tomlkit.parse(
            (Path(__file__).parents[2] / "starbash-recipes" / "starbash.toml").read_text()
        )
        refs = [ref.get("dir") for ref in manifest["repo-ref"]]
        assert "common/crop.toml" in refs

    def test_background_follows_crop(self):
        import tomlkit

        recipe = Path(__file__).parents[2] / "starbash-recipes" / "graxpert" / "background.toml"
        doc: Any = tomlkit.parse(recipe.read_text())
        assert doc["stages"][0]["inputs"][0]["after"] == "crop"


class TestMergeStarsRecipe:
    """Tests that the merge_stars recipe is wired correctly."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = Path(__file__).parents[2] / "starbash-recipes" / "post" / "merge_stars.toml"
        return tomlkit.parse(recipe.read_text())

    def test_parameter_default(self):
        doc = self._load_recipe()
        params = {p["name"]: p for s in doc["stages"] for p in s.get("parameters", [])}
        assert "merge_star_stretch" not in params
        assert params["stretch"]["default"] == 1000.0

    def test_stage_uses_siril_after_veralux(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        assert stage["name"] == "merge_stars"
        assert stage["tool"]["name"] == "siril"
        assert stage["inputs"][0]["after"] == "veralux.*"
        assert stage["inputs"][0]["multiplex"] is True

    def test_only_processes_starless_inputs(self):
        doc = self._load_recipe()
        requires = doc["stages"][0]["inputs"][0]["requires"]
        filename_reqs = [r for r in requires if r["kind"] == "filename"]
        assert len(filename_reqs) == 1
        assert "starless" in filename_reqs[0]["value"]
        assert filename_reqs[0].get("mode", "include") == "include"

    def test_screen_blends_scaled_stars(self):
        doc = self._load_recipe()
        script = doc["stages"][0]["script"]
        # asinh preserves background; autostretch would lift it.
        assert "asinh -human {parameters.stretch}" in script
        assert "merge_star_amount" not in script
        assert "1 - (1 - $starless$) * (1 - $stars$)" in script

    def test_output_named_merged(self):
        doc = self._load_recipe()
        outputs = doc["stages"][0]["outputs"]
        assert len(outputs) == 1
        names = list(outputs[0]["name"])
        assert len(names) == 1
        assert "merged_" in names[0]

    def test_stage_sorts_after_veralux(self):
        from starbash.stages import sort_stages

        doc = self._load_recipe()
        merge = doc["stages"][0]
        veralux = {"name": "veralux", "inputs": [{"after": "starnet.*"}]}
        ordered = sort_stages([merge, veralux])
        names = [s.get("name") for s in ordered]
        assert names.index("veralux") < names.index("merge_stars")


class TestBroadbandPaletteRecipe:
    """Tests that the broadband palette recipe is wired correctly."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = Path(__file__).parents[2] / "starbash-recipes" / "palette" / "broadband.toml"
        return tomlkit.parse(recipe.read_text())

    def test_siril_pass_through(self):
        doc = self._load_recipe()
        stage = doc["stages"][0]
        assert stage["name"] == "palette_broadband"
        assert stage["tool"]["name"] == "siril"
        # The palette follows the *role*, so it works with either denoiser
        # (doc/plans/stage-roles.md §6).
        assert stage["inputs"][0]["after"] == "denoise"
        assert list(stage["outputs"][0]["name"]) == ["broadband.fits"]

    def test_multiplexed(self):
        doc = self._load_recipe()
        assert doc["stages"][0]["inputs"][0]["multiplex"] is True

    def test_inverted_metadata_filter(self):
        doc = self._load_recipe()
        requires = doc["stages"][0]["inputs"][0]["requires"]
        metadata_reqs = [r for r in requires if r["kind"] == "metadata"]
        assert len(metadata_reqs) == 1
        assert metadata_reqs[0]["name"] == "filter"
        assert list(metadata_reqs[0]["value"]) == ["HaOiii", "SiiOiii"]
        assert metadata_reqs[0].get("invert") is True
        assert any(r["kind"] == "min_count" for r in requires)

    def test_default_manifest_includes_broadband_recipe(self):
        import tomlkit

        manifest: Any = tomlkit.parse(
            (Path(__file__).parents[2] / "starbash-recipes" / "starbash.toml").read_text()
        )
        refs = [ref.get("dir") for ref in manifest["repo-ref"]]
        assert "palette/broadband.toml" in refs


class TestVeraluxFilter:
    """Tests that VeraLux only stretches starless (not starmask) files."""

    def _load_recipe(self) -> Any:
        import tomlkit

        recipe = (
            Path(__file__).parents[2]
            / "siril-scripts"
            / "processing"
            / "VeraLux_HyperMetric_Stretch.toml"
        )
        return tomlkit.parse(recipe.read_text())

    def test_skips_starmask_via_filename_filter(self):
        doc = self._load_recipe()
        requires = doc["stages"][0]["inputs"][0]["requires"]
        filename_reqs = [r for r in requires if r["kind"] == "filename"]
        assert len(filename_reqs) == 1
        assert filename_reqs[0]["value"] == "starmask"
        assert filename_reqs[0].get("mode", "include") == "exclude"

    def test_follows_starnet_or_palette_broadband(self):
        doc = self._load_recipe()
        assert doc["stages"][0]["inputs"][0]["after"] == "(starnet|palette_broadband).*"


class TestStarnetTool:
    """Tests for StarnetTool.is_available / missing_message (Siril StarNet plugin detection)."""

    def _make_config(self, parent: Path, starnet_exe: str, version: str = "1.4") -> Path:
        """Create a Siril config directory under ``parent`` holding one versioned config file."""
        config_dir = parent / "siril"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / f"config.{version}.ini").write_text(
            f"[core]\nextension=.fit\nstarnet_exe={starnet_exe}\n"
        )
        return config_dir

    @staticmethod
    def _make_exe(tmp_path: Path) -> Path:
        """Create a real (dummy) ``starnet2``, since the probe checks existence."""
        executable = tmp_path / "bin" / "starnet2"
        executable.parent.mkdir(exist_ok=True)
        executable.write_text("starnet")
        return executable

    def _new_tool(self, monkeypatch, siril_available: bool = True):
        """A tool with its real config-directory search in place (the two OS paths stubbed)."""
        from starbash.tool import base, starnet

        tool = starnet.StarnetTool()
        # Force the base ExternalTool availability probe to a known value.
        monkeypatch.setattr(
            base.ExternalTool, "is_available", property(lambda self: siril_available)
        )
        return tool

    def _make_tool(self, monkeypatch, config_dirs: Path | list[Path], siril_available: bool):
        tool = self._new_tool(monkeypatch, siril_available)
        # Give the probe a fixed directory list.  Besides letting a test pick the
        # native/flatpak search order, this keeps a real Siril config on the machine
        # running the tests out of the result.
        dirs = [config_dirs] if isinstance(config_dirs, Path) else list(config_dirs)
        monkeypatch.setattr(tool, "_siril_config_dirs", lambda: dirs)
        return tool

    def test_available_when_starnet_configured(self, tmp_path, monkeypatch):
        # The configured path has to exist: Siril would fail on a stale one, so a
        # non-empty string in the config file is not enough to call StarNet usable.
        executable = self._make_exe(tmp_path)
        config_dir = self._make_config(tmp_path, str(executable))
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        assert tool.is_available is True

    def test_available_when_configured_name_is_on_path(self, tmp_path, monkeypatch):
        # A bare command name is resolved by Siril itself, so look it up on the PATH.
        config_dir = self._make_config(tmp_path, "starnet2")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: "/somewhere/starnet2")
        assert tool.is_available is True

    def test_unavailable_when_configured_path_is_gone(self, tmp_path, monkeypatch):
        """A configured-but-deleted exe is a real failure, and must say so.

        This is the common case in practice: Starbash writes the path it finds on
        the PATH, so StarNet's removal leaves a setting that looks configured but
        points at nothing.
        """
        # Use a path under tmp_path rather than a real system location: a dev
        # container may well have StarNet installed at e.g. /usr/bin/starnet2, and
        # this test must not depend on the host's package state to exercise a
        # dangling setting.
        gone_exe = str(tmp_path / "gone" / "starnet2")
        config_dir = self._make_config(tmp_path, gone_exe)
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)

        assert tool.is_available is False
        message = tool.missing_message()
        assert gone_exe in message
        assert "no longer exists" in message
        # The install is gone from the machine entirely (nothing on the PATH either),
        # so the message has to lead with that - pointing Siril at "your StarNet
        # install" would send the user looking for one that is not there.
        assert "StarNet is not installed" in message

        # We must not silently rewrite a path the user (or we) chose - only a
        # blank setting is ever filled in.
        parser = configparser.ConfigParser()
        parser.read(config_dir / "config.1.4.ini")
        assert parser.get("core", "starnet_exe") == gone_exe

    def test_unavailable_when_starnet_exe_blank(self, tmp_path, monkeypatch):
        config_dir = self._make_config(tmp_path, "")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)
        assert tool.is_available is False
        # The explanation is now owned by missing_message() and reported at a log
        # level matching the tool's severity (see Tool.preflight), so a probe stays
        # silent - the GUI/CLI decide how loud to be.  With no StarNet on the PATH
        # either, the fix is to install it, not to configure Siril.
        assert "StarNet is not installed" in tool.missing_message()
        assert tool.install_url == "https://starnetastro.com/cli-tools/"

    def test_message_says_not_installed_only_when_starnet_is_really_absent(
        self, tmp_path, monkeypatch
    ):
        """A StarNet we *can* find must not be reported as not installed.

        Siril writes its config file the first time it runs, so a machine where
        Starbash finds ``starnet2`` but there is no config file to record it in has
        nothing left to fix on StarNet's side: telling the user to download it again
        would be wrong, and the Siril-side setup is the real problem.
        """
        executable = self._make_exe(tmp_path)
        config_dir = tmp_path / "siril"
        config_dir.mkdir()
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        assert tool.is_available is False
        message = tool.missing_message()
        assert "StarNet is not enabled in Siril" in message
        assert "not installed" not in message

    def test_configures_starnet_from_path(self, tmp_path, monkeypatch, caplog):
        config_dir = self._make_config(tmp_path, "")
        executable = tmp_path / "bin" / "starnet2"
        executable.parent.mkdir()
        executable.write_text("starnet")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        with caplog.at_level(logging.WARNING):
            assert tool.is_available is True

        parser = configparser.ConfigParser()
        parser.read(config_dir / "config.1.4.ini")
        assert parser.get("core", "starnet_exe") == str(executable.resolve())
        assert "Added starnet2" in caplog.text
        assert str(executable.resolve()) in caplog.text

    def test_configures_starnet_from_windows_default_path(self, tmp_path, monkeypatch):
        """Windows uses StarNet's default installer path when it is not on PATH."""
        from starbash.tool import starnet

        config_dir = self._make_config(tmp_path, "")
        executable = tmp_path / "StarNet2" / "bin" / "starnet2.exe"
        executable.parent.mkdir(parents=True)
        executable.write_text("starnet")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(starnet.sys, "platform", "win32")
        monkeypatch.setattr(starnet, "STARNET_WINDOWS_PATH", executable)

        assert tool.is_available is True

        parser = configparser.ConfigParser()
        parser.read(config_dir / "config.1.4.ini")
        assert parser.get("core", "starnet_exe") == str(executable.resolve())

    def test_does_not_overwrite_existing_starnet_config(self, tmp_path, monkeypatch):
        # Even a stale setting is left alone (only a blank one is ever filled in).
        # It no longer counts as configured, though - reporting it is the point.
        configured_path = "/configured/starnet2"
        config_dir = self._make_config(tmp_path, configured_path)
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: "/path/starnet2")

        assert tool.is_available is False

        parser = configparser.ConfigParser()
        parser.read(config_dir / "config.1.4.ini")
        assert parser.get("core", "starnet_exe") == configured_path

        # StarNet itself *is* installed (it is on the PATH above), so the message has
        # to be the "this setting points at nothing" one - the opposite of the case
        # where no StarNet can be found at all.
        message = tool.missing_message()
        assert configured_path in message
        assert "not installed" not in message

    def test_unavailable_when_no_config_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "siril"
        config_dir.mkdir()
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        assert tool.is_available is False

    def test_unavailable_when_siril_missing(self, tmp_path, monkeypatch):
        config_dir = self._make_config(tmp_path, "/usr/bin/starnet2")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=False)
        assert tool.is_available is False

    def test_result_is_cached(self, tmp_path, monkeypatch):
        executable = self._make_exe(tmp_path)
        config_dir = self._make_config(tmp_path, str(executable))
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        assert tool.is_available is True

        calls = {"n": 0}
        original = tool._starnet_configured

        def counting():
            calls["n"] += 1
            return original()

        monkeypatch.setattr(tool, "_starnet_configured", counting)
        assert tool.is_available is True
        assert calls["n"] == 0  # cached, not re-probed

    # --- invalidating the cached probe (the wizard's *Re-check*) ---------------

    def test_invalidate_availability_reprobes(self, tmp_path, monkeypatch):
        """*Re-check* has to see a StarNet that was installed meanwhile.

        ``is_available`` caches its first answer in ``_starnet_available`` - a field of
        this class, which the inherited ``invalidate_availability()``
        (``_is_available = None``) does not touch - so without the override the tool
        would answer "missing" for the rest of the session.
        """
        config_dir = self._make_config(tmp_path, "")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)
        assert tool.is_available is False

        # The user installs StarNet while Starbash is running: it is on the PATH now.
        executable = self._make_exe(tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))
        assert tool.is_available is False  # still the cached answer

        tool.invalidate_availability()

        assert tool.is_available is True

    def test_invalidate_availability_clears_the_dangling_path(self, tmp_path, monkeypatch):
        """A repaired setting stops being described as the dead path it used to be.

        ``_starnet_dangling`` records what the *last* probe tripped over, so it has to
        be dropped with the cached answer: otherwise a re-check that now succeeds would
        still be carrying the stale path into the next ``missing_message()``.
        """
        gone_exe = str(tmp_path / "gone" / "starnet2")
        config_dir = self._make_config(tmp_path, gone_exe)
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        executable = self._make_exe(tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        assert tool.is_available is False
        assert gone_exe in tool.missing_message()
        assert tool._starnet_dangling == gone_exe

        # The user points Siril at the StarNet that is actually there.
        self._make_config(tmp_path, str(executable))
        tool.invalidate_availability()

        assert tool.is_available is True
        assert tool._starnet_dangling is None

    # --- which Siril config directory is read and written ----------------------

    def test_flatpak_config_is_scanned(self, tmp_path, monkeypatch):
        """A flatpak Siril reads its config from inside its sandbox.

        This is the gap the probe used to have: flatpak gives Siril a private config
        home (``~/.var/app/org.siril.Siril/config/siril``), so reading only
        ``~/.config/siril`` reported StarNet as unconfigured for a flatpak user even
        when Siril was perfectly able to run it.
        """
        executable = self._make_exe(tmp_path)
        flatpak_dir = self._make_config(tmp_path / "flatpak", str(executable))
        # The native directory exists (Siril was run once as a distro package) but
        # holds no config file of its own.
        native_dir = tmp_path / "native" / "siril"
        native_dir.mkdir(parents=True)

        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        assert tool.is_available is True

    def test_setting_in_either_directory_is_honoured(self, tmp_path, monkeypatch):
        """Every directory is read, so neither install hides the other's setting."""
        executable = self._make_exe(tmp_path)

        native_dir = self._make_config(tmp_path / "native", "")
        flatpak_dir = self._make_config(tmp_path / "flatpak", str(executable))
        tool = self._make_tool(monkeypatch, [native_dir, flatpak_dir], siril_available=True)
        assert tool.is_available is True

        native_dir = self._make_config(tmp_path / "native2", str(executable))
        flatpak_dir = self._make_config(tmp_path / "flatpak2", "")
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        assert tool.is_available is True

    def test_a_dangling_setting_does_not_hide_a_usable_one(self, tmp_path, monkeypatch):
        """One directory holding a dead path must not mask the other's live one."""
        executable = self._make_exe(tmp_path)
        flatpak_dir = self._make_config(tmp_path / "flatpak", str(tmp_path / "gone" / "starnet2"))
        native_dir = self._make_config(tmp_path / "native", str(executable))
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)

        assert tool.is_available is True

    def test_flatpak_config_is_where_a_found_starnet_is_recorded(self, tmp_path, monkeypatch):
        """The live directory is the one written to - the flatpak one here.

        Siril has to be *told* about a ``starnet2`` Starbash found on the PATH, and
        for the flatpak app that setting is only read from its sandbox config.
        """
        executable = self._make_exe(tmp_path)
        flatpak_dir = self._make_config(tmp_path / "flatpak", "")
        native_dir = tmp_path / "native" / "siril"
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        assert tool.is_available is True

        parser = configparser.ConfigParser()
        parser.read(flatpak_dir / "config.1.4.ini")
        assert parser.get("core", "starnet_exe") == str(executable.resolve())
        # The other install's directory is left completely alone (no file invented).
        assert not (native_dir / "config.1.4.ini").exists()

    def test_only_the_live_directory_is_written_to(self, tmp_path, monkeypatch):
        """With a config file in both directories, only the first one is filled in."""
        executable = self._make_exe(tmp_path)
        native_dir = self._make_config(tmp_path / "native", "")
        flatpak_dir = self._make_config(tmp_path / "flatpak", "")
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        assert tool.is_available is True

        flatpak_parser = configparser.ConfigParser()
        flatpak_parser.read(flatpak_dir / "config.1.4.ini")
        assert flatpak_parser.get("core", "starnet_exe") == str(executable.resolve())
        native_parser = configparser.ConfigParser()
        native_parser.read(native_dir / "config.1.4.ini")
        assert native_parser.get("core", "starnet_exe") == ""

    def test_newest_config_version_in_the_live_directory_is_used(self, tmp_path, monkeypatch):
        """Siril reads the config file matching its own version, so the newest wins."""
        executable = self._make_exe(tmp_path)
        flatpak_dir = self._make_config(tmp_path / "flatpak", "", version="1.2")
        self._make_config(tmp_path / "flatpak", "", version="1.4")
        native_dir = self._make_config(tmp_path / "native", "")
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: str(executable))

        assert tool.is_available is True

        newer = configparser.ConfigParser()
        newer.read(flatpak_dir / "config.1.4.ini")
        assert newer.get("core", "starnet_exe") == str(executable.resolve())
        older = configparser.ConfigParser()
        older.read(flatpak_dir / "config.1.2.ini")
        assert older.get("core", "starnet_exe") == ""

    def test_probe_logs_the_directories_it_looked_in(self, tmp_path, monkeypatch, caplog):
        """A probe stays silent, except for the diagnostic that explains a miss."""
        flatpak_dir = tmp_path / "flatpak" / "siril"
        native_dir = tmp_path / "native" / "siril"
        tool = self._make_tool(monkeypatch, [flatpak_dir, native_dir], siril_available=True)
        monkeypatch.setattr("shutil.which", lambda name: None)

        with caplog.at_level(logging.DEBUG):
            assert tool.is_available is False

        assert str(flatpak_dir) in caplog.text
        assert str(native_dir) in caplog.text
        assert "not found on the PATH" in caplog.text

    # --- the directory search itself -------------------------------------------

    def _make_search_tool(self, monkeypatch, native: Path, flatpak: Path, siril_command: str):
        """A tool that exercises the *real* search, with its two OS paths stubbed."""
        from starbash.tool import starnet

        monkeypatch.setattr(
            starnet.StarnetTool, "executable_path", property(lambda self: siril_command)
        )
        tool = self._new_tool(monkeypatch)
        monkeypatch.setattr(tool, "_siril_config_dir", lambda: native)
        monkeypatch.setattr(tool, "_siril_flatpak_config_dir", lambda: flatpak)
        return tool

    def test_flatpak_directory_is_preferred_for_a_flatpak_siril(self, tmp_path, monkeypatch):
        from starbash.tool import starnet

        native = tmp_path / "config" / "siril"
        flatpak = tmp_path / "sandbox" / "config" / "siril"
        monkeypatch.setitem(starnet.Tool.Preferences, "siril", {})
        tool = self._make_search_tool(monkeypatch, native, flatpak, starnet.SIRIL_FLATPAK_APP_ID)

        # The sandbox directory comes first, so a StarNet we discover is recorded in
        # the config file the flatpak Siril actually reads.
        assert tool._siril_config_dirs() == [flatpak, native]

    def test_native_directory_is_preferred_for_a_native_siril(self, tmp_path, monkeypatch):
        from starbash.tool import starnet

        native = tmp_path / "config" / "siril"
        flatpak = tmp_path / "sandbox" / "config" / "siril"
        monkeypatch.setitem(starnet.Tool.Preferences, "siril", {})
        tool = self._make_search_tool(monkeypatch, native, flatpak, "siril-cli")

        # Both are still searched - a user who migrated to flatpak keeps an old native
        # config around, and it must not become the one that gets written to.
        assert tool._siril_config_dirs() == [native, flatpak]

    def test_siril_path_override_marks_the_flatpak(self, tmp_path, monkeypatch):
        """``userconfig.toml`` documents naming the flatpak launcher in ``siril.path``."""
        from starbash.tool import starnet

        native = tmp_path / "config" / "siril"
        flatpak = tmp_path / "sandbox" / "config" / "siril"
        # The resolved command is a plain one: only the override says "flatpak".
        tool = self._make_search_tool(monkeypatch, native, flatpak, "siril-cli")
        monkeypatch.setitem(
            starnet.Tool.Preferences,
            "siril",
            {"path": "flatpak run --command=siril-cli org.siril.Siril"},
        )

        assert tool._siril_config_dirs() == [flatpak, native]

    def test_identical_directories_are_not_scanned_twice(self, tmp_path, monkeypatch):
        """Both names can resolve to one directory (an XDG config inside a sandbox)."""
        same = tmp_path / "siril"
        tool = self._make_search_tool(monkeypatch, same, same, "siril-cli")

        assert tool._siril_config_dirs() == [same]

    def test_native_config_dir_drops_the_author_folder(self, monkeypatch):
        """``_siril_config_dir`` must pass ``appauthor=False`` to platformdirs.

        On Windows platformdirs appends the app author (which defaults to the app
        name) *and* the app name, so ``PlatformDirs("siril")`` would resolve to
        ``AppData\\Local\\siril\\siril`` — a doubled folder.  Siril keeps its config
        in ``AppData\\Local\\siril`` (single level), so the author directory must be
        dropped.  ``appauthor`` is ignored on Linux/macOS, so this is safe everywhere.
        """
        from starbash.tool import starnet

        captured: dict = {}

        class _FakePlatformDirs:
            def __init__(self, appname, **kwargs):
                captured["appname"] = appname
                captured["kwargs"] = kwargs

            @property
            def user_config_dir(self):
                return "/fake/config/siril"

        monkeypatch.setattr(starnet, "PlatformDirs", _FakePlatformDirs)

        assert starnet.StarnetTool._siril_config_dir() == Path("/fake/config/siril")
        assert captured["appname"] == "siril"
        assert captured["kwargs"].get("appauthor") is False


class TestRecipeParameterDefaults:
    """Check that recipe script parameter references are declared.

    Parameters may intentionally omit a default.  The rc-astro tool treats an
    unset parameter as an omitted option and uses its own built-in default, so
    the test must not require every referenced parameter to have a TOML default.
    """

    @staticmethod
    def _recipe_files() -> list[Path]:
        import glob

        root = Path(__file__).parents[2]
        patterns = ["starbash-recipes/**/*.toml", "siril-scripts/processing/*.toml"]
        files: list[Path] = []
        for pattern in patterns:
            files.extend(Path(p) for p in glob.glob(str(root / pattern), recursive=True))
        return sorted(files)

    @staticmethod
    def _referenced_params(stage) -> set[str]:
        import re

        chunks: list[str] = []
        script = stage.get("script")
        if isinstance(script, str):
            chunks.append(script)
        elif isinstance(script, list):
            chunks.extend(str(x) for x in script)

        tool = stage.get("tool", {})
        tool_params = tool.get("parameters") if hasattr(tool, "get") else None
        if isinstance(tool_params, dict):
            chunks.extend(str(v) for v in tool_params.values())

        # Matches both `{parameters.x}` and expression forms like `str(parameters.x)`.
        return set(re.findall(r"parameters\.([A-Za-z_][A-Za-z0-9_]*)", "\n".join(chunks)))

    def test_referenced_parameters_are_declared(self):
        import tomlkit
        from toml_repo.repo import Repo

        from starbash.parameters import ParameterStore

        problems: list[str] = []
        for f in self._recipe_files():
            doc = tomlkit.parse(f.read_text())
            stages = doc.get("stages")
            if not stages:
                continue
            repo = Repo(f)
            for stage in stages:
                referenced = self._referenced_params(stage)
                if not referenced:
                    continue
                store = ParameterStore()
                store.add_parameters_from_stage(repo, stage)
                declared = {
                    param.name
                    for param in store._parameters
                    if param.stage_name == stage.get("name")
                }
                for name in referenced:
                    if name not in declared:
                        problems.append(
                            f"{f.name}:{stage.get('name')} references "
                            f"{{parameters.{name}}} but it is not declared"
                        )

        assert not problems, "Recipe parameters missing defaults:\n" + "\n".join(problems)
