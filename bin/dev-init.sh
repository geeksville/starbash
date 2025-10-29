#!/bin/bash

set -e

echo "Setting up for a developer config..."
poetry run sb user name "Kevin Hester"
poetry run sb user email "kevinh@geeksville.com"
poetry run sb repo add ./images/from_asiair
poetry run sb repo add ./images/from_seestar
poetry run sb repo add ./images/from_astroboy