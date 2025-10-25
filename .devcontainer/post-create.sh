#!/usr/bin/env bash
set -e

export USER=`whoami`

# the devcontainer mount of vscode/.local/share implicity makes the owner root (which is bad)
echo "Fixing permissions"

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

echo "installing siril flatpak..."

# Install Siril (as non-root user)
# Note: this must be done here, if done in Dockerfile it doesn't work - bcause dbus is not yet running
# https://github.com/flatpak/flatpak/issues/5076

flatpak --user remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y flathub org.siril.Siril

# Let siril see /tmp
flatpak --user override --filesystem=/tmp org.siril.Siril

echo "setup poetry..."

# Setup poetry build env
poetry completions bash >> ~/.bash_completion

# Setup initial poetry venv
poetry install