#!/usr/bin/env bash
set -e

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# Setup initial poetry venv (we store it in project so we can add the sb/starbash scripts to the path)
poetry config virtualenvs.in-project true --local
poetry install
export PATH="$PWD/.venv/bin:$PATH"


