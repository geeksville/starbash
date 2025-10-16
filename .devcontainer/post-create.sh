#!/usr/bin/env bash
set -e

export USER=`whoami`

# the devcontainer mount of vscode/.local/share implicity makes the owner root (which is bad)
echo "Fixing permissions"
# Some containers might not have a .local directory at all, don't fail in that case
mkdir -p ~/.local
sudo chown -R $USER ~/.local

echo "source .devcontainer/on-shell-start.sh" >> ~/.bashrc

# Install Siril (as non-root user)
# Note: this must be done here, if done in Dockerfile it doesn't work - for unknown reasons ;-)

# UGH FIXME, this worked once but now it doesn't so for now we just grant /run/dbus accesss from the host
# work around for flatpak in docker bug: https://github.com/flatpak/flatpak/issues/5076#issuecomment-1425841966
# ENV FLATPAK_SYSTEM_HELPER_ON_SESSION=foo

flatpak --user remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y flathub org.siril.Siril

# Let siril see /tmp
flatpak --user override --filesystem=/tmp org.siril.Siril

# Install graxpert and pipx (must be done post Dockerfile)
pip install --user --break-system-packages pipx
pipx install graxpert[cpuonly]