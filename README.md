# Starbash

![PyPI - Version](https://img.shields.io/pypi/v/starbash)
![GitHub branch check runs](https://img.shields.io/github/check-runs/geeksville/starbash/main)

 ![app icon](https://github.com/geeksville/starbash/blob/main/img/icon.png "Starbash: Astrophotography workflows simplified")

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

## Supported commands

* setup - configure for you via a brief guided process
* info - show user preferences location and other app info

* repo add file/path|URL
* repo remove REPONAME|REPONUM
* repo list
* repo reindex REPONAME|REPONUM|all

* user analytics on|off - turn analytics collection on/off
* user name "Your Name" - used for attribution in generated images
* user email "foo@blah.com" - used for attribution in generated images

* selection any - remove any filters on targets, sessions, etc...
* selection target TARGETNAME
* selection date op DATE - limit to sessions in the specified date range
* selection - list information about the current selection

* target - list targets (filtered based on the current selection)

* session- list sessions (filtered based on the current selection)

* instrument - list instruments (filtered based on the current selection)

* filter - list all filters found in current selection

* export dirs|BIAS|LIGHT|DARK|FLAT [DIRLOC]

* process auto
* process masters - generate master flats, darks, biases from any raws that are available

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
