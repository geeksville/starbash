#!/usr/bin/env bash

set -e

echo "Note: Currently this script needs to be run on the host OS because it needs podman"

echo "Discarding old volumes (to prevent accidental use)..."
# Discarding old vlumes
podman rm -f starbash-test-data || true
podman volume prune -f || true # make sure we don't use old test-data

echo "Building container..."

# Build the "data container" and tag it
# docker build -t ghcr.io/geeksville/starbash/test-data:latest .
podman build --load -t ghcr.io/geeksville/starbash/test-data:latest .

echo "Push to ghcr.io..."

# Log in to the GitHub Container Registry (using our github credentials)
source .env

# note: if this command fails the nasty fix is probably
# cp ~/.docker/config.json ~/.docker/config.json.backup && echo '{}' > ~/.docker/config.json
podman login ghcr.io -u geeksville --password-stdin <<< $GHCR_GH_TOKEN

# Push your data to the ghcr
podman push ghcr.io/geeksville/starbash/test-data:latest

