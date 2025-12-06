# This is a set of justfile recipes for developer tasks

default:
    just --list

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

# wipe install and do standard reinit
common-init: clean-cache clean-config clean-masters install-completion
    echo "Reiniting a developer config..."
    sb user name "Kevin Hester"
    sb user email "kevinh@geeksville.com"
    sb repo add --master ./images/masters
    sb repo add --processed ./images/processed

# Use our 'big' test database
reinit-big: common-init
    sb repo add ./images/from_asiair
    sb repo add ./images/from_seestar
    sb repo add ./images/from_astroboy
    sb info
    sb select list --brief

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

# process one typical session that is at least not huge
process-one: select-si-ha process

# Process all images
process-all: select-any process

# Process the currently failing test
process-fail: select-any
    sb select target m31 # m13 # ngc6960
    sb --debug process auto

db-browse:
    # via poetry --dev
    harlequin -a sqlite -r ~/.local/share/starbash/db.sqlite3

db-browse-gui:
    sqlitebrowser ~/.local/share/starbash/db.sqlite3

# just add the asiair repo if looking for a demo of adding a repo

# instead of pulling graxpert from pypi, use the local checkout
use-local-graxpert:
    poetry add --editable ./GraXpert --extras cpuonly

use-pypi-graxpert:
    poetry remove GraXpert
    poetry add graxpert --extras cpuonly

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
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

# standard quick test
test:
    poetry run pytest # test must pass

# a slow through test
test-slow: test process-one

test-integration:
    poetry run pytest -m integration -n 0 -v

