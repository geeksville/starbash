#!/bin/bash
set -e

# (b) Quit with an error if an argument isn't provided or isn't a directory
if [ -z "$1" ] || [ ! -d "$1" ]; then
    echo "Error: You must provide a valid directory path." >&2
    exit 1
fi

SRCDIR=$1
echo "Preparing Siril for processing directory $SRCDIR"
SRCDIR=$(realpath "$SRCDIR")

# Create the directory only if it doesn't exist
mkdir -p siril_work
rm -r siril_work/*
cd siril_work

mkdir lights flats biases

ln -s "$SRCDIR/LIGHT/"* lights
ln -s "$SRCDIR/FLAT/"* flats
ln -s "$SRCDIR/BIAS/"* biases

echo "Workspace successfully prepared."
