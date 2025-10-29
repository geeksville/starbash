# Starbash

[![PyPI - Version](https://img.shields.io/pypi/v/starbash)](https://pypi.org/project/starbash/)
[![GitHub branch check runs](https://img.shields.io/github/check-runs/geeksville/starbash/main)](https://github.com/geeksville/starbash/actions)
[![codecov](https://codecov.io/github/geeksville/starbash/graph/badge.svg?token=47RE10I7O1)](https://codecov.io/github/geeksville/starbash)

 ![app icon](https://raw.githubusercontent.com/geeksville/starbash/refs/heads/main/img/icon.png "Starbash: Astrophotography workflows simplified")

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
* Uses Siril and Graxpert for its pre-processing operations (support for Pixinsight based recipes will probably be coming at some point...)
* The target report can be used to auto generate a human friendly 'postable/sharable' report about that image
* Target reports are sharable so that you can request comments by others and others can rerender with different settings

## Installing

Currently the easiest way to install this command-line based tool is to install is via [pipx](https://pipx.pypa.io/stable/).  If you don't already have pipx and you have python installed, you can auto install it by running "pip install --user pipx."  If you don't have python installed see the pipx link for pipx installers for any OS.

Once pipx is installed just run:

```
pipx install starbash
  installed package starbash 0.1.3, installed using Python 3.12.3
  These apps are now globally available
    - sb
    - starbash
done! ✨ 🌟 ✨
```

FIXME - add getting started instructions (possibly with a screenshare video)

## Supported commands

### Repository Management
- `sb repo [--verbose]` - List installed repos (use `-v` for details)
- `sb repo add <filepath|URL>` - Add a repository
- `sb repo remove <REPONUM>` - Remove the indicated repo from the repo list
- `sb repo reindex [--force] [REPONUM]` - Reindex the specified repo (or all repos if none specified)

### User Preferences
- `sb user name "Your Name"` - Set name for attribution in generated images
- `sb user email "foo@example.com"` - Set email for attribution in generated images
- `sb user analytics <on|off>` - Turn analytics collection on/off
- `sb user reinit` - Configure starbash via a brief guided process

### Selection & Filtering
- `sb select` - Show information about the current selection
- `sb select list` - List sessions (filtered based on the current selection)
- `sb select any` - Remove all filters (select everything)
- `sb select target <TARGETNAME>` - Limit selection to the named target
- `sb select telescope <TELESCOPENAME>` - Limit selection to the named telescope
- `sb select date <after|before|between> <DATE> [DATE]` - Limit to sessions in the specified date range
- `sb select export SESSIONNUM DESTDIR` - Export the images for indicated session number into the specified directory (or current directory if not specified).  If possible symbolic links are used, if not the files are copied.

## Not yet supported commands

### Setup & Configuration
- `sb info` - Show user preferences location and other app info
- `sb info target` - List targets (filtered based on the current selection)
- `sb info telescope` - List instruments (filtered based on the current selection)
- `sb info filter` - List all filters found in current selection

### Export & Processing
- `sb process siril` - Generate Siril directory tree and run Siril GUI
- `sb process auto` - Automatic processing
- `sb process masters` - Generate master flats, darks, and biases from available raw frames

## Supported tools (now)

* Siril
* Graxpert
* Python (you can add python code to recipes if necessary)

## Supported tools (future?)

* Pixinsight?
* Autostakkert?

## Developing

We try to make this project useful and friendly.  If you find problems please file a github issue.
We accept pull-requests and enjoy discussing possible new development directions via github issues.  If you might want to work on this, just describe what your interests are and we can talk about how to get it merged.

Project members can access crash reports [here](https://geeksville.sentry.io/insights/projects/starbash/?project=4510264204132352).