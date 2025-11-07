#!/usr/bin/env bash
set -e

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc
echo "source .devcontainer/on-shell-start.sh" >> ~/.zshrc

# Setup initial poetry venv (we store it in project so we can add the sb/starbash scripts to the path)
# already done and persistent
# poetry config virtualenvs.in-project true --local
poetry install

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# zsh completions - write to zsh function directory
mkdir -p ~/.zfunc
poetry completions zsh > ~/.zfunc/_poetry

# not yet tested
# just --completions zsh > ~/.zfunc/_just

# for zsh completions: Add to fpath and enable completions if not already present
if ! grep -q "fpath+=~/.zfunc" ~/.zshrc; then
    echo 'fpath+=~/.zfunc' >> ~/.zshrc
    echo 'autoload -Uz compinit && compinit' >> ~/.zshrc
fi
