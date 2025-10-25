#!/usr/bin/env bash
set -e

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# Setup initial poetry venv
poetry install