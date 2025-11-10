# This is a set of justfile recipes for developer tasks

default:
    just --list

clean-cache:
    rm -rf ~/.cache/starbash

clean-config:
    rm -f ~/.local/share/starbash/db.sqlite3
    rm -f ~/.config/starbash/starbash.toml

clean-masters:
    rm -rf ~/.local/share/starbash/masters

clean-processed:
    rm -rf ./images/processed

install-completion:
    #!/usr/bin/env zsh
    sb --install-completion

reinit: clean-cache clean-config clean-masters install-completion
    echo "Reiniting a developer config..."
    sb user name "Kevin Hester"
    sb user email "kevinh@geeksville.com"
    sb repo add ./images/from_asiair
    sb repo add ./images/from_seestar
    sb repo add ./images/from_astroboy
    sb repo add --master
    sb repo add --processed ./images/processed
    sb info
    sb select list --brief

reinit-masters: reinit
    sb process masters

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

# test target that has Si and HaOiii filters
select-si-ha:
    sb select any
    sb select target ngc281

# test using just the HaOiii filter
select-ha:
    sb select any
    sb select target ic1396

process:
    sb process auto

# Process all images
process-all: select-any process

db-browse:
    # via poetry --dev
    harlequin -a sqlite -r ~/.local/share/starbash/db.sqlite3

db-browse-gui:
    sqlitebrowser ~/.local/share/starbash/db.sqlite3

# just add the asiair repo if looking for a demo of adding a repo

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
bump-version newver: test
    bin/new-version.sh {{newver}}

_lint:
    poetry run ruff check src/ tests/

# Run type checking with pyright (same errors as Pylance in VS Code)
_typecheck:
    poetry run pyright src/

# Run all linting checks (ruff + pyright)
check: _lint _typecheck

format:
    poetry run ruff format src/ tests/

lint-fix:
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

test:
    poetry run pytest # test must pass