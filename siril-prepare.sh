#!/bin/bash
set -e

# (b) Quit with an error if an argument isn't provided or isn't a directory
if [ -z "$1" ] || [ ! -d "$1" ]; then
    echo "Error: You must provide a valid directory path." >&2
    exit 1
fi

SRCDIR=$(realpath "$1")

if [ ! -d "$SRCDIR/LIGHT" ]; then
    echo "Error: '$SRCDIR' does not contain a LIGHT directory." >&2
    exit 1
fi

echo "Preparing Siril for processing directory $SRCDIR"

DESTDIR=~/Pictures/telescope/siril_work/

# Create the directory only if it doesn't exist
mkdir -p $DESTDIR
cd $DESTDIR
rm -r $DESTDIR/*

mkdir lights flats biases

# Keep results on the persistent volume
mkdir -p "$SRCDIR/results"

ln -s "$SRCDIR/LIGHT/"* lights
ln -s "$SRCDIR/FLAT/"* flats
ln -s "$SRCDIR/BIAS/"* biases
ln -s "$SRCDIR/results" results

echo "Workspace successfully prepared."
