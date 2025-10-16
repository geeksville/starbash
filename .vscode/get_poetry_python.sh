#!/bin/bash
# This script finds and executes the python interpreter within the poetry virtual environment.
set -e

# Get the full path to the virtualenv's python executable
POETRY_PYTHON_PATH=$(poetry env info --path)/bin/python

exec "$POETRY_PYTHON_PATH" "$@"