"""Tests for the tool module."""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from starbash.tool import (
    GraxpertBuiltinTool,
    GraxpertExternalTool,
    PythonScriptError,
    PythonTool,
    RCAstroTool,
    SirilTool,
    Tool,
    ToolError,
    _SafeFormatter,
    expand_context,
    expand_context_unsafe,
    make_safe_globals,
    strip_comments,
    tool_run,
    tools,
)
from starbash.tool.base import tool_run_streaming
from starbash.tool.rcastro import parse_json_line


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

            def _run(self, cwd: str, commands: str, context: dict = {}, **kwargs) -> None:
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


class TestToolRun:
    """Tests for tool_run function."""

    def test_tool_run_success(self):
        """Test successful tool execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Use a real command - echo should work on all platforms
            tool_run("echo hello", temp_dir)
            # If we get here without exception, the command succeeded

    @pytest.mark.skipif(os.name == "nt", reason="Shell quoting with spaces not supported on Windows cmd.exe")
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

            # Test with properly quoted path - this should work
            tool_run(f'"{symlink_path}" -c "pass"', temp_dir)

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
        #siril_commands = ["siril-cli", "siril", "org.siril.Siril"]
        #siril_available = any(shutil.which(cmd) for cmd in siril_commands)
        #if not siril_available:
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
            pass

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

        def fake_stream(cmd, cwd, on_line, timeout=None, log_out=None):
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

    def _load_recipe(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2]
            / "starbash-recipes"
            / "rc-astro"
            / "blur-exterminator.toml"
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

    def _load_recipe(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2]
            / "starbash-recipes"
            / "rc-astro"
            / "noise-exterminator.toml"
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

    def _load_recipe(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2] / "starbash-recipes" / "common" / "starnet.toml"
        )
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

    def _load_recipe(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2] / "starbash-recipes" / "common" / "crop.toml"
        )
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

        assert params["crop_percent"]["default"] == 90
        assert params["rotate_deg"]["default"] == 0
        assert stage["outputs"][0]["auto"]["prefix"] == "crop_"

    def test_default_manifest_includes_crop_recipe(self):
        import tomlkit

        manifest = tomlkit.parse(
            (
                Path(__file__).parents[2]
                / "starbash-recipes"
                / "starbash.toml"
            ).read_text()
        )
        refs = [ref.get("dir") for ref in manifest["repo-ref"]]
        assert "common/crop.toml" in refs

    def test_background_follows_crop(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2]
            / "starbash-recipes"
            / "graxpert"
            / "background.toml"
        )
        doc = tomlkit.parse(recipe.read_text())
        assert doc["stages"][0]["inputs"][0]["after"] == "crop"


class TestMergeStarsRecipe:
    """Tests that the merge_stars recipe is wired correctly."""

    def _load_recipe(self):
        import tomlkit

        recipe = (
            Path(__file__).parents[2] / "starbash-recipes" / "post" / "merge_stars.toml"
        )
        return tomlkit.parse(recipe.read_text())

    def test_parameter_default(self):
        doc = self._load_recipe()
        params = {p["name"]: p for s in doc["stages"] for p in s.get("parameters", [])}
        assert "merge_star_stretch" not in params
        assert params["stretch"]["default"] == 800.0

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


class TestVeraluxFilter:
    """Tests that VeraLux only stretches starless (not starmask) files."""

    def _load_recipe(self):
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


class TestStarnetTool:
    """Tests for StarnetTool.is_available (Siril StarNet plugin detection)."""

    def _make_config(self, tmp_path: Path, starnet_exe: str) -> Path:
        config_dir = tmp_path / "siril"
        config_dir.mkdir()
        (config_dir / "config.1.4.ini").write_text(
            f"[core]\nextension=.fit\nstarnet_exe={starnet_exe}\n"
        )
        return config_dir

    def _make_tool(self, monkeypatch, config_dir: Path, siril_available: bool):
        from starbash.tool import base, starnet

        tool = starnet.StarnetTool()
        monkeypatch.setattr(tool, "_siril_config_dir", lambda: config_dir)
        # Force the base ExternalTool availability probe to a known value.
        monkeypatch.setattr(
            base.ExternalTool, "is_available", property(lambda self: siril_available)
        )
        return tool

    def test_available_when_starnet_configured(self, tmp_path, monkeypatch):
        config_dir = self._make_config(tmp_path, "/usr/bin/starnet2")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        assert tool.is_available is True

    def test_unavailable_when_starnet_exe_blank(self, tmp_path, monkeypatch, caplog):
        config_dir = self._make_config(tmp_path, "")
        tool = self._make_tool(monkeypatch, config_dir, siril_available=True)
        with caplog.at_level(logging.WARNING):
            assert tool.is_available is False
        assert "StarNet is not enabled" in caplog.text

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
        config_dir = self._make_config(tmp_path, "/usr/bin/starnet2")
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





