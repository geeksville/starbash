#!/usr/bin/env bash
set -e

export USER=`whoami`

# the devcontainer mount of vscode/.local/share implicity makes the owner root (which is bad)
echo "Fixing permissions"

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

echo "setup poetry..."

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# Setup initial poetry venv
poetry install