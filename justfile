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

make-movies:
    echo "This script allows developers to generate new 'vhs' demo movies for the github README."
    echo "Note: it can't work in the devcontainer you must run it on the host side."
    echo "On host run 'brew install vhs'"

    vhs doc/vhs/sample-session.tape
    # Not needed - for the time being we just use the gif in our repo
    # vhs publish doc/vhs/sample-session.gif

bump-version newver: test
    bin/new-version.sh {{newver}}

lint:
    poetry run ruff check src/ tests/

format:
    poetry run ruff format src/ tests/

lint-fix:
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

test:
    poetry run pytest # test must pass