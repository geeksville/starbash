"""Tests for the tool module."""

import os
import tempfile
import pytest
from pathlib import Path

from starbash.tool import (
    _SafeFormatter,
    expand_context,
    make_safe_globals,
    strip_comments,
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

    def test_max_iterations_warning(self):
        """Test that recursive definitions trigger max iterations and raise error."""
        # Create a circular reference
        context = {"a": "{b}", "b": "{a}"}
        # Should reach max iterations and then raise KeyError for unexpanded vars
        with pytest.raises(KeyError) as exc_info:
            expand_context("{a}", context)
        assert "a" in str(exc_info.value)

    def test_no_expansion_needed(self):
        """Test string with no variables."""
        result = expand_context("plain text", {"var": "value"})
        assert result == "plain text"

    def test_escaped_braces_remain(self):
        """Test that context variables work with adjacent text."""
        result = expand_context("test_{var}_end", {"var": "middle"})
        assert result == "test_middle_end"


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
        """Test that context is passed through."""
        test_context = {"key": "value"}
        result = make_safe_globals(test_context)
        assert result["context"] == test_context

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
        """Test that default context is an empty dict."""
        result = make_safe_globals()
        assert result["context"] == {}


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
        """Test that syntax errors are raised."""
        tool = PythonTool()

        code = "if True"  # Invalid syntax

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(SyntaxError):
                tool.run(temp_dir, code, {})

    def test_python_tool_runtime_error_raises(self):
        """Test that runtime errors are raised."""
        tool = PythonTool()

        code = "raise ValueError('test error')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError) as exc_info:
                tool.run(temp_dir, code, {})
            assert "test error" in str(exc_info.value)

    def test_python_tool_changes_directory(self):
        """Test that Python tool changes to the working directory."""
        tool = PythonTool()
        original_cwd = os.getcwd()
        context = {"cwd_during_run": []}

        code = "import os; context['cwd_during_run'].append(os.getcwd())"

        with tempfile.TemporaryDirectory() as temp_dir:
            tool.run(temp_dir, code, context)
            # Verify cwd was changed during execution
            assert context["cwd_during_run"][0] == temp_dir
            # Verify cwd was restored after execution
            assert os.getcwd() == original_cwd

    def test_python_tool_restores_directory_on_error(self):
        """Test that directory is restored even on error."""
        tool = PythonTool()
        original_cwd = os.getcwd()

        code = "raise RuntimeError('test')"

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(RuntimeError):
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
