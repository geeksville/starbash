#!/usr/bin/env bash
set -e

echo "source /workspaces/starbash/.devcontainer/on-shell-start.sh" >> ~/.bashrc
echo "source /workspaces/starbash/.devcontainer/on-shell-start.sh" >> ~/.zshrc

# Fix git credential helper to use container's gh path instead of host's homebrew path
git config --global --unset-all credential.'https://github.com'.helper 2>/dev/null || true
git config --global --add credential.'https://github.com'.helper '!/usr/bin/gh auth git-credential'
git config --global --unset-all credential.'https://gist.github.com'.helper 2>/dev/null || true
git config --global --add credential.'https://gist.github.com'.helper '!/usr/bin/gh auth git-credential'

# Setup initial poetry venv (we store it in project so we can add the sb/starbash scripts to the path)
# already done and persistent
# poetry config virtualenvs.in-project true --local
poetry install --with dev

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# zsh completions - write to zsh function directory
mkdir -p ~/.zfunc
poetry completions zsh > ~/.zfunc/_poetry

# install git hooks
poetry run pre-commit install

# just completions
just --completions bash >> ~/.bash_completion
just --completions zsh > ~/.zfunc/_just

# for zsh completions: Add to fpath and enable completions if not already present
if ! grep -q "fpath+=~/.zfunc" ~/.zshrc; then
    echo 'fpath+=~/.zfunc' >> ~/.zshrc
    echo 'autoload -Uz compinit && compinit' >> ~/.zshrc
fi
