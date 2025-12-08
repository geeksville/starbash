#!/usr/bin/env bash
set -euo pipefail

# new-version.sh — bump project version with Poetry and push a matching git tag
# Usage:
#   bin/new-version.sh [version|bump-type]
#
# Examples:
#   bin/new-version.sh          # auto-bump patch version (0.2.0 → 0.2.1)
#   bin/new-version.sh patch    # same as no args
#   bin/new-version.sh minor    # bump minor (0.2.0 → 0.3.0)
#   bin/new-version.sh major    # bump major (0.2.0 → 1.0.0)
#   bin/new-version.sh 0.2.0    # set explicit version
#
# This will:
#   1) Ensure a clean git working tree
#   2) Set the project version in pyproject.toml via `poetry version`
#   3) Commit the change
#   4) Create an annotated tag v0.2.0
#   5) Push the commit and the tag to origin

usage() {
  echo "Usage: $0 [--dry-run] [version|bump-type]" >&2
  echo "" >&2
  echo "Options:" >&2
  echo "  --dry-run   Show what would be done without making changes" >&2
  echo "" >&2
  echo "Examples:" >&2
  echo "  $0          # auto-bump patch version (0.2.0 → 0.2.1)" >&2
  echo "  $0 patch    # same as no args" >&2
  echo "  $0 minor    # bump minor (0.2.0 → 0.3.0)" >&2
  echo "  $0 major    # bump major (0.2.0 → 1.0.0)" >&2
  echo "  $0 0.2.0    # set explicit version" >&2
  echo "  $0 --dry-run minor  # show what would happen for minor bump" >&2
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

# Check for --dry-run flag
DRY_RUN=false
if [[ ${1:-} == "--dry-run" ]]; then
  DRY_RUN=true
  shift
fi

# Default to patch bump if no argument provided
VERSION_ARG="${1:-patch}"

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

# Ensure clean working tree (skip check in dry-run mode)
if [[ $DRY_RUN == false ]]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: working tree has uncommitted changes. Commit or stash before running." >&2
    git status --porcelain
    exit 1
  fi
fi

# Bump or set the version
echo "Setting version via Poetry (argument: $VERSION_ARG)..."
poetry version "$VERSION_ARG"

# Get the new version that was just set
VERSION=$(poetry version -s)
echo "New version: $VERSION"

# Ensure the tag doesn't already exist
TAG="v$VERSION"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Error: tag $TAG already exists" >&2
  exit 1
fi

# Commit version bump
# Include pyproject.toml and poetry.lock if present
FILES=(pyproject.toml)
[[ -f poetry.lock ]] && FILES+=(poetry.lock)

if [[ $DRY_RUN == true ]]; then
  echo "[DRY RUN] Would add and commit: ${FILES[*]}"
  echo "[DRY RUN] Would commit with message: Release: $VERSION"
  echo "[DRY RUN] Would create tag $TAG with message: starbash $VERSION"
  if [[ -d starbash-recipes ]]; then
    echo "[DRY RUN] Would tag starbash-recipes submodule with $TAG"
  fi
  echo "[DRY RUN] Would push commit to origin"
  echo "[DRY RUN] Would push tag $TAG to origin"
  echo "[DRY RUN] Would run: poetry install"
  echo ""
  echo "[DRY RUN] To actually perform these actions, run without --dry-run"
else
  git add "${FILES[@]}"
  git commit -m "Release: $VERSION"

  echo "Creating tag $TAG..."
  git tag -a "$TAG" -m "starbash $VERSION"

  # Tag the starbash-recipes submodule if it exists
  if [[ -d starbash-recipes ]]; then
    echo "Tagging starbash-recipes submodule with $TAG..."
    (
      cd starbash-recipes
      git tag -f -a "$TAG" -m "starbash $VERSION"
      if git remote get-url origin >/dev/null 2>&1; then
        git push -f origin "$TAG"
        echo "Pushed tag $TAG to starbash-recipes"
      else
        echo "Warning: starbash-recipes has no origin remote, tag created locally only"
      fi
    )
  fi

  echo "Pushing commit and tag to origin..."
  git push origin HEAD
  git push origin "$TAG"

  echo "Installing locally"
  poetry install

  echo "Done. Created and pushed tag $TAG."
fi


