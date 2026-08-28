# This is a set of [just](https://github.com/casey/just) recipes for developer tasks

default:
    just --list

init-devcontainer: install-starnet install-rc-astro use-workspace-config

clean-cache:
    rm -rf ~/.cache/starbash

# erase the DB
clean-db:
    rm -f ~/.local/share/starbash/db.sqlite3

# erase user settings and DB
clean-config: clean-db
    rm -f ~/.config/starbash/starbash.toml

clean-masters:
    rm -rf ./images/masters

clean-processed:
    rm -rf ./images/processed

install-completion:
    #!/usr/bin/env zsh
    sb --install-completion

# Install the starnet binaries
install-starnet:
    #!/usr/bin/env bash
    [ -f /usr/bin/starnet2 ] && exit 0
    wget -O /tmp/starnet.deb https://download.starnetastro.com/StarNet2_linux_2.5.4-0214_ORT_x64.deb
    mkdir -p ~/packages
    sudo dpkg -i /tmp/starnet.deb
    rm /tmp/starnet.deb
    echo "Installed starnet binaries"

# install the rc-astro CLI tool 
install-rc-astro:
    #!/usr/bin/env bash
    [ -f /usr/local/bin/rc-astro ] && exit 0
    wget -O /tmp/rcastro.sh https://www.rc-astro-cdn.com/clients/2.6.4/rc-astro-cli-2.6.4-linux-x64.sh
    chmod a+x /tmp/rcastro.sh
    /tmp/rcastro.sh
    sudo /tmp/rc-astro-cli/install.sh
    echo "Installed rc-astro CLI tool"

# Run starnet (for testing)
starnet infile outfile="starless.tif" stride="256":
    LD_LIBRARY_PATH=~/packages/starnet ~/packages/starnet/starnet++ {{infile}} {{outfile}} {{stride}}

# Use our local git submodule version of the recipies
use-local-recipes:
    sb repo add /workspaces/starbash/starbash-recipes

# Use the github version
use-standard-recipes:
    sb repo remove file:///workspaces/starbash/starbash-recipes

# configure for a developer (myself) with my name/email and local repos
reinit-dev:
    echo "Reiniting a developer config..."
    sb user name "Kevin Hester"
    sb user email "kevinh@geeksville.com"
    sb repo add --master /mnt/pool/big/kevinh/telescope/masters | true
    sb repo add --processed /mnt/pool/big/kevinh/telescope/processed | true

# wipe install and do standard reinit
common-init: clean-cache clean-config clean-masters install-completion use-local-recipes reinit-dev

# Use our 'big' test database and try not to lose settings if we can help it.  
reinit-big: # do subtasks below to guarantee ordering
    just use-workspace-config
    just use-usb-cache
    just reinit-dev
    just use-local-recipes
    sb repo add /mnt/pool/big/kevinh/telescope/from_asiair
    sb repo add /mnt/pool/big/kevinh/telescope/from_seestar
    sb repo add /mnt/pool/big/kevinh/telescope/from_astroboy
    sb info
    sb select list --brief

# Use a remote cache for starbash temp files
use-remote-cache:
    #!/usr/bin/env bash
    target=/mnt/pool/big/kevinh/telescope/starbash/cache
    mkdir -p "$target"
    mkdir -p ~/.cache
    [ "$(readlink ~/.cache/starbash)" = "$target" ] || { rm -rf ~/.cache/starbash && ln -s "$target" ~/.cache/starbash; }

# Use a USB cache for starbash temp files
use-usb-cache:
    #!/usr/bin/env bash
    target=/mnt/fast_stick/starbash/cache
    mkdir -p "$target"
    mkdir -p ~/.cache
    [ "$(readlink ~/.cache/starbash)" = "$target" ] || { rm -rf ~/.cache/starbash && ln -s "$target" ~/.cache/starbash; }

# keep the config/cache files in the workspace so that it lives even if the container is recreated
use-workspace-config:
    #!/usr/bin/env bash
    cwd=$(pwd)
    mkdir -p ~/.cache ~/.config ~/.local/share
    [ "$(readlink ~/.cache/starbash)" = "$cwd/.cache" ] || { rm -rf ~/.cache/starbash && ln -s "$cwd/.cache" ~/.cache/starbash; }
    [ "$(readlink ~/.config/starbash)" = "$cwd/.config" ] || { rm -rf ~/.config/starbash && ln -s "$cwd/.config" ~/.config/starbash; }
    [ "$(readlink ~/.local/share/starbash)" = "$cwd/.local" ] || { rm -rf ~/.local/share/starbash && ln -s "$cwd/.local" ~/.local/share/starbash; }

# our small standard set of test images (from ghcr.io/geeksville/starbash/test-data:latest)
reinit: common-init
    sb repo add /test-data/dwarf3
    sb repo add /test-data/asiair
    sb repo add /test-data/nina
    sb repo add /test-data/seestar
    sb info
    sb select list --brief

process-masters:
    sb process masters

reinit-masters: reinit process-masters

select-any:
    sb --verbose select any

# handy way of splitting my old test sessions from new
select-after:
    sb select date after 2025-08-01

# nina test target with no filter - just flats
select-no-filter:
    sb select any
    sb select target m45

# test target with just a simple filter on a Seestar (no flats, no bias)
select-seestar:
    sb select any
    sb select target Sadr

select-seestar-ir:
    sb select any
    sb select target m81

# select my current test target
select-current:
    sb select any
    #sb select target "ngc6888"
    sb select target "sh2-91"

# test target that has Si and HaOiii filters
select-si-ha:
    sb select any
    sb select target m20 # or for a longer test: ngc281

# test using just the HaOiii filter
select-ha:
    sb select any
    sb select target ic1396

# select a small/fast to process target
select-small: select-seestar-ir

process:
    sb process auto


# Use my external USB disk for scratch
process-big:
    STARBASH_CACHE_DIR=/mnt/fast_stick/starbash_tmp sb process auto

# process one typical session that is at least not huge
process-one: select-si-ha process

# Process all images
process-all: select-any process

# Process the currently failing test
process-fail: select-any
    sb select target m31 # m13 # ngc6960
    sb --debug process auto

code-coverage:
    poetry run pytest --cov --cov-report=html
    open htmlcov/index.html

db-browse:
    # via poetry --dev
    harlequin -a sqlite -r ~/.local/share/starbash/db.sqlite3

db-browse-gui:
    sqlitebrowser ~/.local/share/starbash/db.sqlite3

# just add the asiair repo if looking for a demo of adding a repo

# instead of pulling graxpert from pypi, use the local checkout
use-graxpert-local:
    poetry add --editable ./GraXpert --extras cpuonly

use-graxpert-pypi:
    poetry remove GraXpert
    poetry add graxpert --extras cpuonly

# instead of pulling toml-repo from pypi, use the local submodule
use-toml-repo-local:
    poetry add --editable ./toml-repo

use-toml-repo-pypi:
    poetry remove toml-repo
    poetry add toml-repo

# genera demo videos for the README
movies: movie-sample movie-process-auto movie-process-siril

# generate demo of auto processing
movie-process-auto: select-any
    #!/usr/bin/env bash
    export PROMPT="> "
    vhs doc/vhs/process-auto.tape

# demo of export to siril
movie-process-siril:
    #!/usr/bin/env bash
    export PROMPT="> "
    sb select target m20
    vhs doc/vhs/process-siril.tape
    rm -r ./siril-process

# generate video of basic browsing
movie-sample: select-any
    #!/usr/bin/env bash
    export PROMPT="> "
    vhs doc/vhs/sample-session.tape
    # Not needed - for the time being we just use the gif in our repo
    # vhs publish doc/vhs/sample-session.gif

# release a new version pypi
bump-version newver="patch": test
    bin/new-version.sh {{newver}}

_lint:
    poetry run ruff check src/ tests/

# Run type checking with basedpyright (same errors as Pylance in VS Code)
_typecheck:
    poetry run basedpyright src/

# Run all linting checks (ruff + basedpyright)
lint: format _lint _typecheck

format:
    # Remove trailing whitespace
    sed -i 's/[[:space:]]*$//' src/**/*.py tests/**/*.py
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

# standard quick test
test:
    poetry run pytest # test must pass

# Regenerate and serve the local Jekyll report site.
site-view:
    sb publish
    jekyll build --source ~/.local/state/starbash/publish/site --destination ~/.local/state/starbash/publish/site/_site
    jekyll serve --source ~/.local/state/starbash/publish/site --destination ~/.local/state/starbash/publish/site/_site

# a slow through test
test-slow: test process-one

test-integration:
    poetry run pytest -m integration -n 0 -v

# Test in-place siril script usage
test-scripts:
    sb select target m13 # An easy test target from the small dataset
    # sb repo add ./siril-scripts/processing/VeraLux_HyperMetric_Stretch.toml
    sb process auto

# show dependency graph of tasks (requires graphviz installed)
depends:
    # options must precede the task name, and use = form:
    sb process doit graph --reverse --horizontal --show-subtasks --output=/tmp/tasks.dot process_all
    dot -Tsvg /tmp/tasks.dot -o /tmp/tasks.svg     # or -Tpng
    open /tmp/tasks.svg

#
# The following is for experimenting with Textual UI stuff
#

# Run the textual demo app
textual-demo:
    python -m textual

textual-code-demo:
    python ./textual/examples/code_browser.py

# Run starbash in UI mode
ui:
    python ./src/starbash/ui/main.py

# Get a readable copy of the textual source for reference
download-textual:
    -git clone https://github.com/Textualize/textual.git reference/textual

# Download a copy of siril for experimenting with script export
download-siril:
    -git clone https://gitlab.com/free-astro/siril.git reference/siril