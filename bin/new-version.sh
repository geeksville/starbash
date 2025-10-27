#!/usr/bin/env bash
set -euo pipefail

# new-version.sh — bump project version with Poetry and push a matching git tag
# Usage:
#   bin/new-version.sh 0.2.0
#
# This will:
#   1) Ensure a clean git working tree
#   2) Set the project version in pyproject.toml via `poetry version`
#   3) Commit the change
#   4) Create an annotated tag v0.2.0
#   5) Push the commit and the tag to origin

usage() {
  echo "Usage: $0 <version>" >&2
  echo "Example: $0 0.2.0" >&2
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

VERSION="$1"
# Basic semver with optional pre-release/build metadata allowed
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][A-Za-z0-9][A-Za-z0-9.-]*)?$ ]]; then
  echo "Error: version must look like 0.2.0 or 0.2.0-rc.1" >&2
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required" >&2
  exit 1
fi
if ! command -v poetry >/dev/null 2>&1; then
  echo "Error: poetry is required (install from https://python-poetry.org/docs/)" >&2
  exit 1
fi

# Move to repo root
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

echo "Repo: $REPO_ROOT"

# Ensure we have an 'origin' remote
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Error: no 'origin' remote configured" >&2
  exit 1
fi

# Ensure clean working tree
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree has uncommitted changes. Commit or stash before running." >&2
  git status --porcelain
  exit 1
fi

# Ensure the tag doesn't already exist
TAG="v$VERSION"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Error: tag $TAG already exists" >&2
  exit 1
fi

echo "Setting version to $VERSION via Poetry..."
poetry version "$VERSION"

NEW_VER=$(poetry version -s)
if [[ "$NEW_VER" != "$VERSION" ]]; then
  echo "Error: poetry version now reports '$NEW_VER' which doesn't match '$VERSION'" >&2
  exit 1
fi

# Commit version bump
# Include pyproject.toml and poetry.lock if present
FILES=(pyproject.toml)
[[ -f poetry.lock ]] && FILES+=(poetry.lock)

git add "${FILES[@]}"
git commit -m "Release: $VERSION"

echo "Creating tag $TAG..."
git tag -a "$TAG" -m "starbash $VERSION"

echo "Pushing commit and tag to origin..."
git push origin HEAD
git push origin "$TAG"

echo "Done. Created and pushed tag $TAG."
