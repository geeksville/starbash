#!/bin/bash

# --- Add any commands you want to run for each new shell ---

# Set Ptyxis terminal tab title to "starbash-dev" (if under that terminal)
if [[ -n "$PTYXIS_VERSION" ]]; then
    echo -ne "\033]0;starbash-dev\007"
fi

echo "🚀 Starbash dev shell started!"

cd /workspaces/starbash

# To find siril and other flatpaks
export PATH="$PATH:$HOME/.local/share/flatpak/exports/bin/"

# to reach our sb command
export PATH="$PWD/.venv/bin:$PATH"

# Limit OpenBLAS threads to prevent resource warnings when running tests
# GraXpert's numpy/scipy dependencies use OpenBLAS which tries to create too many threads
export OPENBLAS_NUM_THREADS=4

