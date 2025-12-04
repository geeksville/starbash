#!/bin/bash

# --- Add any commands you want to run for each new shell ---

echo "🚀 Starbash dev shell started!"

# To find siril and other flatpaks
export PATH="$PATH:$HOME/.local/share/flatpak/exports/bin/"

# to reach our sb command
export PATH="$PWD/.venv/bin:$PATH"

# Limit OpenBLAS threads to prevent resource warnings when running tests
# GraXpert's numpy/scipy dependencies use OpenBLAS which tries to create too many threads
export OPENBLAS_NUM_THREADS=4