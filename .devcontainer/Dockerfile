# Run inside a recent debian based image with python3, pip3, git and sudo installed
# This is the same as the debian version but used to test against full ubuntu
FROM mcr.microsoft.com/devcontainers/base:noble

# We use 'user' as the name to match what the zhephyr-build image already created
ARG USERNAME=vscode

## Setup a user with sudo support
USER root

RUN apt update

# Add core python packages
RUN apt-get -y install --no-install-recommends python3 python3-pip python3-venv python-is-python3 python3-tk sudo git 

# Create a non-root user if one doesn't exist, and give it sudo rights
RUN if ! id -u ${USERNAME} > /dev/null 2>&1; then \
        groupadd --gid 1000 ${USERNAME} && \
        useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ${USERNAME} && \
        echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}-nopasswd; \
    fi

# Install Siril
RUN apt-get update
RUN apt-get -y --no-install-recommends install flatpak graphviz xdot python3-pip python3
RUN flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
RUN flatpak install -y flathub org.siril.Siril

# Let siril see /tmp
RUN flatpak override --filesystem=/tmp org.siril.Siril

USER ${USERNAME}