# Astroglue
A tool for automating/standardizing/sharing astrophotography workflows.

# Current status

Not quite ready 😊.  But making good progress.

See my personal [TODO](TODO.md) file.  I'll be looking for pre-alpha testers/feedback soon.

## features

* Automatically recognizes and auto-parses the default NINA, Asiair and Seestar raw file repo layouts (adding support for other layouts is easy)
* Automatically performs preprocessing on OSC (broadband, narrowband or dual Duo filter), Mono (LRGB, SHO) data
* Multisession support by default (including auto selection of correct flats, biases and dark frames)
* Generates a per target report/config file which can be customized if the detected defaults are not what you want
* 'Recipes' provide repeatable/human-readable/sharable descriptions of all processing steps
* 'Repos' can contain raw files, generated masters, preprocessed files, or recipes.
* Repos can be on the local disk or shared via HTTPS/github/etc.  This is particularly useful for recipe repos

## Supported tools

* Siril
* Graxpert

# Future status

## Supported tools

* Pixinsight?
* Autostakkert?

## Features

* The target report can be used to auto generate a human friendly 'postable/sharable' report about that image
* Target reports are sharable so that you can request comments by others and others can rerender with different settings
