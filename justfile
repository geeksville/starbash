# This is a set of justfile recipes for developer tasks

default:
    just --list

clear-cache:
    rm -rf ~/.cache/starbash

clear-config:
    rm -f ~/.local/share/starbash/db.sqlite3
    rm -f ~/.config/starbash/starbash.toml

reinit: clear-cache clear-cache
    #!/usr/bin/env zsh
    echo "Reiniting a developer config..."
    rm -rf ~/Documents/starbash/repos/master
    sb --install-completion
    sb user name "Kevin Hester"
    sb user email "kevinh@geeksville.com"
    sb repo add ./images/from_asiair
    sb repo add ./images/from_seestar
    sb repo add ./images/from_astroboy
    sb repo add --master
    sb repo add --processed ./images/processed
    sb process masters
    sb info
    sb select list --brief

select-any:
    sb --verbose select any

# handy way of splitting my old test sessions from new
select-after:
    sb select date after 2025-08-01

select-test-target:
    sb select any
    sb select target ngc281

process: select-test-target
    sb --force process auto

db-browse:
    sqlitebrowser ~/.local/share/starbash/db.sqlite3

make-movies:
    echo "This script allows developers to generate new 'vhs' demo movies for the github README."
    echo "Note: it can't work in the devcontainer you must run it on the host side."
    echo "On host run 'brew install vhs'"

    vhs doc/vhs/sample-session.tape
    # Not needed - for the time being we just use the gif in our repo
    # vhs publish doc/vhs/sample-session.gif

bump-version newver: test
    bin/new-version {{newver}}

test:
    poetry run pytest # test must pass