# starbash-test-data

This directory contains **large** test data files for the [starbash](https://github.com/geeksville/starbash) project.

The large files are never actually included in the git file.  Rather this project just contains a few scripts
creating a ghcr.io container image with the large files inside it.  If you are a developer and need to modify this container there is a sister script that can be used to download an existing container image, modify it, and then re-upload it.

## Developer instructions

For general ghcr.io info see [here](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

## Create a github "personal access token (classic)"

at https://github.com/settings/tokens
give it at least write:packages and read:packages scope.
Paste the generated token into ./.env as:
```
GH_TOKEN=xxx
```


