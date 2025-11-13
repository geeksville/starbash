#!/usr/bin/env bash

set -e

# Log in to the GitHub Container Registry (using our github credentials)
source .env
docker login ghcr.io -u geeksville --password-stdin <<< $GH_TOKEN

# Build the "data container" and tag it
docker build -t ghcr.io/geeksville/starbash/test-data:latest .

# Push your data to the ghcr
docker push ghcr.io/geeksville/starbash/test-data:latest