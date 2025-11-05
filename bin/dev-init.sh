#!/bin/bash

set -e

echo "Setting up for a developer config..."
sb --install-completion
sb user name "Kevin Hester"
sb user email "kevinh@geeksville.com"
#sb repo add ./images/from_asiair
#sb repo add ./images/from_seestar
sb repo add ./images/from_astroboy
sb repo add --master
sb repo add --processed
sb select target ngc281
sb info
sb select list

