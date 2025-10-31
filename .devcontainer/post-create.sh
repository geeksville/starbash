#!/usr/bin/env bash
set -e

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

# Setup initial poetry venv (we store it in project so we can add the sb/starbash scripts to the path)
# already done and persistent
# poetry config virtualenvs.in-project true --local
poetry install
export PATH="$PWD/.venv/bin:$PATH"

# Setup poetry build env
poetry completions bash >> ~/.bash_completion
