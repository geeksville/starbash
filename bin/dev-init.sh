#!/bin/bash

set -e

echo "Reiniting a developer config..."
rm -f ~/.local/share/starbash/db.sqlite3
rm -f ~/.config/starbash/starbash.toml
rm -rf ~/.cache/starbash
rm -rf ~/Documents/starbash/repos/master
sb --install-completion
sb user name "Kevin Hester"
sb user email "kevinh@geeksville.com"
sb repo add ./images/from_asiair
sb repo add ./images/from_seestar
sb repo add ./images/from_astroboy
sb repo add --master
sb repo add --processed ./images/processed
#sb select target ngc281
sb info
sb select list

