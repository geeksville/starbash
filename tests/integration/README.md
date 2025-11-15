# Integration Tests

This directory contains integration tests that verify the complete starbash workflow using real FITS test data.

## Overview

The integration tests run through a complete workflow:

1. **Add repositories** - Add multiple test data directories containing FITS files
2. **Verify indexing** - Confirm data is indexed and accessible via `sb info` and `sb select list`
3. **Generate masters** - Create master calibration frames using `sb process masters`
4. **Auto-process** - Run automatic processing pipeline using `sb process auto`

Tests are organized into three sequential test classes:
- `TestRepoAddWorkflow` - Add repos and verify data indexing
- `TestProcessMastersWorkflow` - Generate master calibration frames
- `TestProcessAutoWorkflow` - Run automatic processing

Each test class builds upon the state created by previous classes, so test order matters.

## Troubleshooting

### Error: "Integration tests cannot run in parallel!"

If you see this error message:

```
❌ ERROR: Integration tests cannot run in parallel!
Please use: pytest -m integration -n 0
```

This means you forgot to add the `-n 0` flag. Integration tests **must** run sequentially because they build upon each other's state. Simply add `-n 0` to your command:

```bash
pytest -m integration -n 0
```

## Log Output

Integration tests automatically capture all log messages (DEBUG level and higher) to `/tmp/sb-integration-log.txt`. This file is created fresh each time you run integration tests and contains detailed logging information that can be helpful for debugging test failures or understanding the workflow.

To view the log output after running tests:

```bash
# View the entire log file
cat /tmp/integration-logout.txt

# View the last 50 lines
tail -50 /tmp/integration-logout.txt

# Search for specific errors or warnings
grep -i error /tmp/integration-logout.txt
grep -i warning /tmp/integration-logout.txt
```

## Prerequisites

### Test Data Setup

Integration tests require the `/test-data` directory to be available with FITS image data. This directory should contain subdirectories for different data sources:

```
/test-data/
  ├── dwarf3/      # Dwarf II telescope data
  ├── asiair/      # ZWO ASIAir data
  ├── nina/        # N.I.N.A. imaging suite data
  └── seestar/     # Seestar S50 data
```

See `/workspaces/starbash/test-data/README.md` for information on setting up test data using the container image.

### Poetry Environment

Make sure you have the development environment set up:

```bash
poetry install --with dev
```

## Running Integration Tests

**IMPORTANT**: Integration tests **must** run sequentially (not in parallel) because they build upon each other's state. If you forget to add `-n 0`, you'll see a clear error message instructing you to add it.

### Run All Integration Tests

Integration tests are marked with `@pytest.mark.integration` and **excluded by default** because they are slow. These tests must run **sequentially** (not in parallel) because they build upon each other's state:

```bash
# Run only integration tests (sequentially)
pytest -m integration -n 0

# Or with verbose output
pytest -m integration -n 0 -v

# Run specific test file
pytest -m integration -n 0 tests/integration/test_workflow.py
```

**Important**: The `-n 0` flag disables parallel execution, which is **required** because tests build upon accumulated state from previous tests. If you run `pytest -m integration` without `-n 0`, you will get a helpful error message telling you to add it.

### Run Specific Test Classes

To run only one stage of the workflow (still requires sequential execution):

```bash
# Just test repo add workflow
pytest -m integration -n 0 tests/integration/test_workflow.py::TestRepoAddWorkflow

# Just test master frame generation (requires repos to be added first)
pytest -m integration -n 0 tests/integration/test_workflow.py::TestProcessMastersWorkflow

# Just test auto-processing (requires repos and masters)
pytest -m integration -n 0 tests/integration/test_workflow.py::TestProcessAutoWorkflow
```

**Note**: Running individual test classes may fail if earlier stages haven't been run, since tests depend on accumulated state.

### Run Specific Tests

```bash
# Run a single test (may fail if dependencies aren't met)
pytest -m integration -n 0 tests/integration/test_workflow.py::TestRepoAddWorkflow::test_add_dwarf3_repo
```

### Default Test Behavior

By default, integration tests are **excluded** when running `pytest`:

```bash
# This will NOT run integration tests (by default)
pytest

# This will run only unit tests (excludes slow and integration)
pytest tests/unit/
```

To include integration tests in a normal test run:

```bash
# Run all tests including integration (not recommended for CI)
pytest -m ""

# Run unit and integration tests (excluding only slow tests)
pytest -m "not slow"
```

## Test Markers

The project uses pytest markers to categorize tests:

- `slow` - Marks tests as slow (excluded by default)
- `integration` - Marks integration tests requiring `/test-data` (excluded by default)

Both markers are defined in `pyproject.toml` and excluded by default via:
```toml
addopts = "-m 'not slow and not integration' -n auto"
```

## Test Isolation

Integration tests use isolated config and data directories via pytest fixtures:

- **Config directory**: Temporary directory for `starbash.toml` user preferences
- **Data directory**: Temporary directory for `db.sqlite3` and `selection.json`
- **Test data**: Real FITS files from `/test-data` (read-only)

This ensures tests don't interfere with your actual starbash configuration or database.

## Test Structure

### Fixtures (`conftest.py`)

- `test_data_dir` - Session-scoped fixture that checks for `/test-data` and skips if missing
- `workflow_environment` - Class-scoped fixture providing isolated test directories
- `setup_test_environment` - Function-scoped fixture for test isolation
- `mock_analytics` - Mocks Sentry analytics to avoid external calls

### Test Flow

Tests within each class run sequentially and build upon each other:

1. **TestRepoAddWorkflow**
   - Adds each test data repo (dwarf3, asiair, nina, seestar)
   - Verifies `sb info` shows indexed data
   - Verifies `sb select list --brief` shows sessions
   - Confirms repos appear in `sb repo list`

2. **TestProcessMastersWorkflow**
   - Runs `sb process masters`
   - Verifies command completes successfully
   - Checks for expected output messages
   - Confirms database is updated

3. **TestProcessAutoWorkflow**
   - Runs `sb process auto`
   - Verifies command completes successfully
   - Checks for expected processing output
   - Final workflow completion sanity check

If a test fails in an early stage, subsequent stages may also fail as they depend on the accumulated state.

## Troubleshooting

### Tests Are Skipped

If all integration tests are skipped with message "Integration tests require /test-data directory":

- Verify `/test-data` directory exists: `ls -la /test-data`
- Check permissions: `stat /test-data`
- See test-data setup instructions in `/workspaces/starbash/test-data/README.md`

### Tests Fail Early

If tests fail during repo addition:

- Check that test data directories contain valid FITS files
- Verify file permissions allow reading
- Run with `-v` flag for verbose output to see exact error messages

## Development

When adding new integration tests:

1. Mark them with `@pytest.mark.integration`
2. Use `workflow_environment` fixture for shared state
3. Add helpful assertion messages for debugging
4. Document expected behavior and dependencies
5. Test both success and edge cases

Example:
```python
@pytest.mark.integration
def test_my_new_feature(workflow_environment):
    """Test my new feature with real data."""
    result = runner.invoke(app, ["my-command"])
    assert result.exit_code == 0, f"Command failed: {result.stdout}"
```

