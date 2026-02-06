# This is a set of [just](https://github.com/casey/just) recipes for developer tasks

default:
    just --list

# standard test
test:
    poetry run pytest

_lint:
    poetry run ruff check src/ tests/

# Run type checking with basedpyright (same errors as Pylance in VS Code)
_typecheck:
    poetry run basedpyright

# Run all linting checks (ruff + basedpyright)
lint: format _lint _typecheck

format:
    # Remove trailing whitespace
    find src tests -name '*.py' -type f -exec sed -i 's/[[:space:]]*$//' {} +
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

# release a new version to pypi
bump-version newver="patch": test
    bin/new-version.sh {{newver}}
