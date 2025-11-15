#!/usr/bin/env bash

set -e

echo "Building container..."

# Build the "data container" and tag it
docker build -t ghcr.io/geeksville/starbash/test-data:latest .

echo "Push to ghcr.io..."

# Log in to the GitHub Container Registry (using our github credentials)
source .env

# note: if this command fails the nasty fix is probably
# cp ~/.docker/config.json ~/.docker/config.json.backup && echo '{}' > ~/.docker/config.json
docker login ghcr.io -u geeksville --password-stdin <<< $GHCR_GH_TOKEN

# Push your data to the ghcr
docker push ghcr.io/geeksville/starbash/test-data:latest