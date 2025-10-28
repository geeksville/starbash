# Starbash

![PyPI - Version](https://img.shields.io/pypi/v/starbash)
![GitHub branch check runs](https://img.shields.io/github/check-runs/geeksville/starbash/main)

 ![app icon](https://github.com/geeksville/starbash/blob/main/img/icon.png "Starbash: Astrophotography workflows simplified")

A tool for automating/standardizing/sharing astrophotography workflows.

# Current status

Not quite ready 😊.  But making good progress.

See the current [TODO](TODO.md) file for work items.  I'll be looking for pre-alpha testers/feedback soon.

## Current features

* Automatically recognizes and auto-parses the default NINA, Asiair and Seestar raw file repos (adding support for other layouts is easy)
* Multisession support by default (including automatic selection of correct flats, biases and dark frames)
* 'Repos' can contain raw files, generated masters, preprocessed files, or recipes.

## Features coming soon

* Automatically performs **complete** preprocessing on OSC (broadband, narrowband or dual Duo filter), Mono (LRGB, SHO) data.  i.e. give you 'seestar level' auto-preprocessing, so you only need to do the (optional) custom post-processing.
* Generates a per target report/config file which can be customized if the detected defaults or preprocessing are not what you want
* 'Recipes' provide repeatable/human-readable/sharable descriptions of all processing steps
* Repos can be on the local disk or shared via HTTPS/github/etc.  This is particularly useful for recipe repos
* Uses Siril and Graxpert for its pre-processing operations (support for Pixinsight based recipies will probably be coming at some point...)
* The target report can be used to auto generate a human friendly 'postable/sharable' report about that image
* Target reports are sharable so that you can request comments by others and others can rerender with different settings

## Supported commands

### Setup & Configuration
- `sb setup` - Configure starbash via a brief guided process
- `sb info` - Show user preferences location and other app info

### Repository Management
- `sb repo [--verbose]` - List installed repos (use `-v` for details)
- `sb repo add <filepath|URL>` - Add a repository
- `sb repo remove <REPONUM>` - Remove the indicated repo from the repo list
- `sb repo reindex [--force] [REPONUM]` - Reindex the specified repo (or all repos if none specified)

### User Preferences
- `sb user name "Your Name"` - Set name for attribution in generated images
- `sb user email "foo@example.com"` - Set email for attribution in generated images
- `sb user analytics <on|off>` - Turn analytics collection on/off

### Selection & Filtering
- `sb selection` - Show information about the current selection
- `sb selection any` - Remove all filters (select everything)
- `sb selection target <TARGETNAME>` - Limit selection to the named target
- `sb selection telescope <TELESCOPENAME>` - Limit selection to the named telescope
- `sb selection date <after|before|between> <DATE> [DATE]` - Limit to sessions in the specified date range

### Viewing Data
- `sb session` - List sessions (filtered based on the current selection)
- `sb target` - List targets (filtered based on the current selection)
- `sb instrument` - List instruments (filtered based on the current selection)
- `sb filter` - List all filters found in current selection

### Export & Processing
- `sb export <dirs|BIAS|LIGHT|DARK|FLAT> [DIRLOC]` - Export data
- `sb process siril` - Generate Siril directory tree and run Siril GUI
- `sb process auto` - Automatic processing
- `sb process masters` - Generate master flats, darks, and biases from available raw frames

## Supported tools (now)

* Siril
* Graxpert
* Python (you can add python code to recipies if necessary)

## Supported tools (future?)

* Pixinsight?
* Autostakkert?
