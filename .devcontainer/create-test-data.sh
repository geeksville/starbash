#!/usr/bin/env bash
set -e

# Check if the container already exists
if podman container exists starbash-test-data; then
    echo "Container starbash-test-data already exists, skipping creation."
else
    echo "Creating starbash-test-data container from ghcr.io/geeksville/starbash/test-data:latest..."
    podman create --name starbash-test-data ghcr.io/geeksville/starbash/test-data:latest

    # the container has to be started at least once for the volume export to happen
    podman start starbash-test-data

    # give time for the container to be created before VS code checks for it
    sleep 1
fi
