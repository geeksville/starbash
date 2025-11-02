#!/bin/bash

# --- Add any commands you want to run for each new shell ---

echo "🚀 Starbash dev shell started!"

# To find siril and other flatpaks
export PATH="$PATH:$HOME/.local/share/flatpak/exports/bin/"

# to reach our sb command
export PATH="$PWD/.venv/bin:$PATH"