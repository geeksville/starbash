# Run inside a recent debian based image with python3, pip3, git and sudo installed
# This is the same as the debian version but used to test against full ubuntu
FROM mcr.microsoft.com/devcontainers/base:noble

# We use 'user' as the name to match what the zhephyr-build image already created
ARG USERNAME=vscode

## Setup a user with sudo support
USER root

# Add core python packages
RUN apt-get update && apt-get -y install --no-install-recommends \
        python3 python3-pip python3-venv python-is-python3 python3-tk sudo git flatpak sqlitebrowser

# Not yet using docker (we might need docker for using the vhs movie maker)
# RUN apt-get install docker.io

# Create a non-root user if one doesn't exist, and give it sudo rights
RUN if ! id -u ${USERNAME} > /dev/null 2>&1; then \
        groupadd --gid 1000 ${USERNAME} && \
        useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ${USERNAME} && \
        echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}-nopasswd; \
        fi

USER ${USERNAME}

# Some containers might not have a .local directory at all, don't fail in that case
RUN mkdir -p /home/${USERNAME}/.local/bin

# Add the local bin directory to the PATH. For pipx and flatpacks
ENV PATH="/home/${USERNAME}/.local/bin:$HOME/.local/share/flatpak/exports/bin/:${PATH}"

# astropy provides the fitsheader command line tool
RUN pip install --user --no-cache-dir --break-system-packages pipx \
        && pipx install --pip-args=--no-cache-dir graxpert[cpuonly] \
        && pipx install --pip-args=--no-cache-dir poetry astropy

# Install Siril (as non-root user)
# Note: this must be done here, if done in Dockerfile it doesn't work - this env var is a nasty hack to allow
# flatpak inside of Dockerfile.
# https://github.com/flatpak/flatpak/issues/5076
ENV FLATPAK_SYSTEM_HELPER_ON_SESSION=foo
RUN flatpak --user remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
RUN flatpak install --user -y flathub org.siril.Siril
# Let siril see /tmp
RUN flatpak --user override --filesystem=/tmp org.siril.Siril

# Install homebrew (works - but not currently used)
#RUN sudo apt-get install build-essential curl git -y
#RUN NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
#RUN echo >> /home/vscode/.bashrc && \
#    echo 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' >> /home/vscode/.bashrc && \
#    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

# install vhs command-line movie maker (not used - we instead use the docker version)
#RUN brew install vhs

USER root

# Make container smaller.  Do this last, so that if we change the container it is fast to use existing apts
RUN rm -rf /var/lib/apt/lists/*