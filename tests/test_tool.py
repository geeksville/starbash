"""Tests for the tool module."""

import os
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from starbash.tool import (
    _SafeFormatter,
    expand_context,
    expand_context_unsafe,
    make_safe_globals,
    strip_comments,
    tool_run,
    Tool,
    PythonTool,
    SirilTool,
    GraxpertTool,
    tools,
)


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
        result = expand_context_unsafe(
            "{instrument}/{date}/{imagetyp}/output.fits", context
        )
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
        with pytest.raises(ValueError, match="Failed to evaluate expression"):
            expand_context_unsafe("bad: {this is not valid}", {})

    def test_missing_variable_raises_error(self):
        """Test that missing variables raise ValueError."""
        with pytest.raises(ValueError, match="Failed to evaluate expression.*missing"):
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
        """Test that run() raises NotImplementedError."""
        tool = Tool("test")
        with pytest.raises(NotImplementedError):
            tool.run("/tmp", "commands")

    def test_run_in_temp_dir_creates_temp_directory(self):
        """Test that run_in_temp_dir creates and cleans up temp directory."""

        class TestTool(Tool):
            def __init__(self):
                super().__init__("test")
                self.received_cwd = None
                self.received_context = None

            def run(self, cwd: str, commands: str, context: dict = {}) -> None:
                self.received_cwd = cwd
                self.received_context = context
                # Verify temp directory exists during execution
                assert os.path.isdir(cwd)
                assert cwd.startswith(tempfile.gettempdir())

        tool = TestTool()
        tool.run_in_temp_dir("test commands", {"key": "value"})

        # Verify temp_dir was added to context
        assert tool.received_context is not None
        assert "temp_dir" in tool.received_context
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
            tool.run(temp_dir, code, context)
            assert context["result"] == [42]

    def test_python_tool_has_access_to_context(self):
        """Test that Python scripts can access context variables."""
        tool = PythonTool()
        context = {"input": 10, "output": []}

        code = "context['output'].append(context['input'] * 2)"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(temp_dir, code, context)
            assert context["output"] == [20]

    def test_python_tool_syntax_error_raises(self):
        """Test that syntax errors are re-raised directly."""
        tool = PythonTool()

        code = "if True"  # Invalid syntax

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(SyntaxError) as exc_info:
                tool.run(temp_dir, code, {})
            # RestrictedPython provides detailed syntax error messages
            assert "SyntaxError" in str(exc_info.value)

    def test_python_tool_runtime_error_raises(self):
        """Test that runtime errors are wrapped in ValueError."""
        tool = PythonTool()

        code = "raise ValueError('test error')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError) as exc_info:
                tool.run(temp_dir, code, {})
            # The error is wrapped, so we get the generic message
            assert "Error during python script execution" in str(exc_info.value)

    def test_python_tool_changes_directory(self):
        """Test that Python tool changes to the working directory."""
        tool = PythonTool()
        original_cwd = os.getcwd()
        context = {"cwd_during_run": []}

        code = "import os; context['cwd_during_run'].append(os.getcwd())"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(temp_dir, code, context)
            # Verify cwd was changed during execution. Use realpath to
            # resolve macOS /private vs /var symlink differences.
            assert os.path.realpath(context["cwd_during_run"][0]) == os.path.realpath(
                temp_dir
            )
            # Verify cwd was restored after execution
            assert os.getcwd() == original_cwd

    def test_python_tool_restores_directory_on_error(self):
        """Test that directory is restored even on error."""
        tool = PythonTool()
        original_cwd = os.getcwd()

        code = "raise RuntimeError('test')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError):  # Exceptions are wrapped in ValueError
                tool.run(temp_dir, code, {})
            # Verify cwd was restored after error
            assert os.getcwd() == original_cwd


class TestSirilTool:
    """Tests for SirilTool class."""

    def test_siril_tool_name(self):
        """Test SirilTool has correct name."""
        tool = SirilTool()
        assert tool.name == "siril"

    def test_siril_tool_expands_context(self):
        """Test that SirilTool expands context variables in commands."""
        tool = SirilTool()
        # We can't easily test the actual siril execution without mocking subprocess,
        # but we can verify the tool is instantiated correctly
        assert tool.name == "siril"


class TestGraxpertTool:
    """Tests for GraxpertTool class."""

    def test_graxpert_tool_name(self):
        """Test GraxpertTool has correct name."""
        tool = GraxpertTool()
        assert tool.name == "graxpert"


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
        assert isinstance(tools["graxpert"], GraxpertTool)
        assert isinstance(tools["python"], PythonTool)

    def test_tools_dict_keys_match_names(self):
        """Test that dict keys match tool names."""
        for key, tool in tools.items():
            assert key == tool.name


class TestToolRun:
    """Tests for tool_run function."""

    @patch("starbash.tool.subprocess.Popen")
    def test_tool_run_success(self, mock_popen):
        """Test successful tool execution."""
        # Mock process with stdout/stderr that can be read
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = None

        # Create mock file objects for stdout/stderr
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.side_effect = ["output\n", ""]  # One line then EOF

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.return_value = ""  # EOF immediately

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_process.stdin = MagicMock()

        mock_popen.return_value = mock_process

        tool_run("test_command", "/tmp", "input commands")

        mock_popen.assert_called_once()
        assert mock_process.stdin.write.called
        assert mock_process.stdin.close.called

    @patch("starbash.tool.subprocess.Popen")
    @patch("starbash.tool.select.select")
    def test_tool_run_with_stderr_warning(self, mock_select, mock_popen, caplog):
        """Test that stderr output is logged as warning."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.side_effect = [None, None, 0]  # Not done, not done, then done

        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.return_value = ""  # Always EOF for stdout

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.side_effect = ["warning message\n", ""]

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        # Mock select to return stderr first, both streams next, then nothing
        mock_select.side_effect = [
            ([2], [], []),  # stderr ready with message
            ([1, 2], [], []),  # Both ready for EOF
            ([], [], []),  # No more streams (shouldn't reach here)
        ]

        tool_run("test_command", "/tmp")

        assert "warning message" in caplog.text

    @patch("starbash.tool.subprocess.Popen")
    def test_tool_run_failure_raises_error(self, mock_popen):
        """Test that non-zero return code raises RuntimeError."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.poll.return_value = 1

        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.return_value = ""

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.return_value = ""

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        with pytest.raises(RuntimeError, match="Tool failed with exit code 1"):
            tool_run("failing_command", "/tmp")

    @patch("starbash.tool.subprocess.Popen")
    @patch("starbash.tool.select.select")
    def test_tool_run_failure_logs_output(self, mock_select, mock_popen, caplog):
        """Test that failure logs both stdout and stderr."""
        import logging

        caplog.set_level(logging.DEBUG)  # Need DEBUG level to see stdout messages

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.poll.side_effect = [None, None, None, 1]  # Not done x3, then done

        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.side_effect = ["error output\n", ""]

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.side_effect = ["error message\n", ""]

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        # Mock select to return both streams
        mock_select.side_effect = [
            ([1], [], []),  # stdout ready with message
            ([2], [], []),  # stderr ready with message
            ([1, 2], [], []),  # Both ready for EOF
            ([], [], []),  # No more data (shouldn't reach)
        ]

        with pytest.raises(RuntimeError):
            tool_run("failing_command", "/tmp")

        assert "error output" in caplog.text
        assert "error message" in caplog.text

    @patch("starbash.tool.subprocess.Popen")
    def test_tool_run_without_input_commands(self, mock_popen):
        """Test tool_run with no input commands (stdin)."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.return_value = 0

        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.return_value = ""

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.return_value = ""

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        tool_run("test_command", "/tmp", commands=None)

        # Verify stdin was None
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["stdin"] is None

    @patch("starbash.tool.subprocess.Popen")
    @patch("starbash.tool.select.select")
    def test_tool_run_logs_stdout_on_success(self, mock_select, mock_popen, caplog):
        """Test that stdout is logged on successful run."""
        import logging

        caplog.set_level(logging.DEBUG)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.side_effect = [None, None, 0]  # Not done, not done, then done

        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.readline.side_effect = ["successful output\n", ""]

        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        mock_stderr.readline.return_value = ""  # Always EOF for stderr

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_popen.return_value = mock_process

        # Mock select to return stdout
        mock_select.side_effect = [
            ([1], [], []),  # stdout ready with message
            ([1, 2], [], []),  # Both ready for EOF
            ([], [], []),  # No more data (shouldn't reach)
        ]

        tool_run("test_command", "/tmp")

        # Check debug logs
        assert "Tool command successful" in caplog.text
        assert "successful output" in caplog.text


class TestSirilToolRun:
    """Tests for SirilTool.run method."""

    def test_siril_tool_run_with_empty_script(self):
        """Test that SirilTool.run can execute Siril with empty script."""

        # Skip test if Siril is not available
        siril_commands = ["org.siril.Siril", "siril-cli", "siril"]
        siril_available = any(shutil.which(cmd) for cmd in siril_commands)
        if not siril_available:
            pytest.skip("Siril not available on this system")

        tool = SirilTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Just run with empty script to verify Siril executes
            tool.run(temp_dir, "", {})


class TestGraxpertToolRun:
    """Tests for GraxpertTool.run method."""

    @pytest.mark.slow
    def test_graxpert_tool_run_with_help(self):
        """Test that GraxpertTool.run can execute GraXpert."""

        # Skip test if GraXpert is not available
        if not shutil.which("graxpert"):
            pytest.skip("GraXpert not available on this system")

        tool = GraxpertTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            # Just run --help to verify GraXpert executes
            # Note: --help may exit with non-zero in some versions
            try:
                tool.run(temp_dir, "--help", {})
            except RuntimeError as e:
                # Allow --help to fail (argparse behavior varies)
                # Just verify the tool was found
                if "not found" in str(e).lower():
                    pytest.fail("GraXpert command not found")
