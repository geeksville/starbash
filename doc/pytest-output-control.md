# Limiting Pytest Output on Failures

When tests fail and external tools (like Siril or GraXpert) produce verbose output, the test failure messages can be overwhelming with hundreds of lines of captured stdout/stderr.

## Quick Solution

The easiest way to limit output is to use pytest's built-in `--tb` (traceback) option:

```bash
# Show only one line per failure (minimal output)
poetry run pytest --tb=line

# Show short tracebacks (recommended default - already configured)
poetry run pytest --tb=short

# Show full tracebacks (verbose)
poetry run pytest --tb=long

# Hide captured output entirely
poetry run pytest --show-capture=no
```

## Default Configuration

The project's `pyproject.toml` is already configured with `--tb=short` which shows shorter tracebacks than the default. This is set in:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not slow and not integration' -n auto --tb=short -rA"
```

## Recommended Options for Different Scenarios

### 1. **Debugging a specific failing test** (need full output)
```bash
poetry run pytest tests/unit/test_tool.py::test_specific_failure -v --tb=long
```

### 2. **Running full test suite** (want minimal noise)
```bash
poetry run pytest --tb=line -q
```

### 3. **CI/CD environments** (want summary only)
```bash
poetry run pytest --tb=short -rA --maxfail=5
```

### 4. **Investigating tool output issues** (need captured output)
```bash
poetry run pytest tests/unit/test_tool.py -v --tb=long --show-capture=all
```

## Output Format Options

| Option | Description | Use When |
|--------|-------------|----------|
| `--tb=long` | Full tracebacks with all output | Debugging one test |
| `--tb=short` | Shorter tracebacks (default) | Normal development |
| `--tb=line` | One line per failure | Running many tests |
| `--tb=no` | No traceback at all | Just want pass/fail |
| `--show-capture=no` | Hide captured output | Output not needed |
| `-q` | Quiet mode | Minimal terminal output |
| `-v` | Verbose mode | See test names |

## Examples

**Problem:** Test fails with 500 lines of Siril output
```
FAILED tests/unit/test_tool.py::test_siril_processing
... [500 lines of output] ...
```

**Solution 1:** Use `--tb=line` to see only the failure line
```bash
poetry run pytest --tb=line
# Output: FAILED tests/unit/test_tool.py::test_siril_processing - RuntimeError: ...
```

**Solution 2:** Use `--tb=short` to see traceback but not all output
```bash
poetry run pytest --tb=short
# Output: Shows traceback + last ~20 lines of output
```

**Solution 3:** Hide captured output entirely
```bash
poetry run pytest --show-capture=no
# Output: Shows traceback but no captured stdout/stderr
```

## Permanent Configuration

To change the default for your local development,  modify `pyproject.toml` directly (affects all developers):

```toml
[tool.pytest.ini_options]
addopts = "-m 'not slow and not integration' -n auto --tb=line -rA"
```

## Related Resources

- [Pytest documentation on --tb option](https://docs.pytest.org/en/stable/how-to/output.html#modifying-python-traceback-printing)
- [Pytest output control](https://docs.pytest.org/en/stable/reference/reference.html#command-line-flags)
