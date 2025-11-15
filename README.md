# [Starbash](https://github.com/geeksville/starbash)

<img src="https://raw.githubusercontent.com/geeksville/starbash/refs/heads/main/doc/img/icon.jpg" alt="Starbash: Astrophotography workflows simplified" width="30%" align="right" style="margin-bottom: 20px;">

[![PyPI - Version](https://img.shields.io/pypi/v/starbash)](https://pypi.org/project/starbash/)
[![Continuous Integration](https://github.com/geeksville/starbash/actions/workflows/ci.yml/badge.svg)](https://github.com/geeksville/starbash/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/geeksville/starbash/graph/badge.svg?token=47RE10I7O1)](https://codecov.io/github/geeksville/starbash)

A tool for automating/standardizing/sharing astrophotography workflows.

* Automatic - with sensible defaults that you can change as needed.
* Easy - provides a 'seestar-like' starting point for autoprocessing all your sessions (by default).
* Fast - even with large image repositories.  Automatic master bias and flat generation and reasonable defaults.
* Multi-session - by default.  So your workflows can stack from multiple nights (and still use the correct flats etc...).
* Shareable - you can share/use recipes for image preprocessing flows.
* Attribution (by default) - a full set of contributions to final image can be tracked: instrument, raw images, processed-by, scripts-by/version etc...

(This project is currently 'alpha' and missing recipes for some workflows, but adding new recipes is easy and we're happy to help.  Please file a GitHub issue if your images are not auto-processed and we'll work out a fix.)

<br clear="right">

# Current status

This project is still very young - but making good progress 😊!

If you are interested in alpha-testing we ❤️ you.  This README should have enough instructions to get you going, but if you encounter **any** problems please file a github issue and we'll work together to fix them.

![Sample session movie](https://raw.githubusercontent.com/geeksville/starbash/refs/heads/main/doc/vhs/sample-session.gif)

## Current features

* Automatically recognizes and auto-parses the default NINA, Asiair, and Seestar raw file repos (adding support for other layouts is easy).
* Multi-session support by default (including automatic selection of correct flats, biases, and dark frames).
* 'Repos' can contain raw files, generated masters, preprocessed files, or recipes.
* Automatically performs **complete** preprocessing on OSC (broadband, narrowband, or dual Duo filter).  i.e., gives you 'seestar-level' auto-preprocessing, so you only need to do the (optional) custom post-processing.
* Uses Siril recipes for its pre-processing operations (support for Pixinsight-based recipes will probably be coming at some point...).
* Generates a per-target config file which can (eventually) be customized if the detected defaults or preprocessing are not what you want.

## Features coming soon

* Include a stretched 'thumbnail' jpg proof-of-concept render in the output directories
* Support for mono-camera workflows (this alpha version only supports color cameras).
* Generates a per-target report/config file which can be customized if the detected defaults or preprocessing are not what you want.
* 'Recipes' are now user-editable - provides repeatable/human-readable/shareable descriptions of all processing steps.
* Repos can be on the local disk or shared via HTTPS/GitHub/etc.  This is particularly useful for recipe repos.
* Graxpert based recipe stages added (support for Pixinsight-based recipes will probably be coming at some point...).
* The target report can be used to auto-generate a human-friendly 'postable/shareable' report about that image.
* Target reports are shareable so that you can request comments from others and others can rerender with different settings.

See the [TODO](TODO.md) file for work items and approximate schedule.

## Support

If you have questions/ideas please post in the [discussion group](https://github.com/geeksville/starbash/discussions).  If you find bugs please create an [issue](https://github.com/geeksville/starbash/issues).  This is a friendly project.

## Installing

Currently the easiest way to install this command-line based tool is via [pipx](https://pipx.pypa.io/stable/).  If you don't already have pipx and you have Python installed, you can auto-install it by running "pip install --user pipx."  If you don't have Python installed see the pipx link for pipx installers for any OS.

Once pipx is installed just run the following **two** commands (the `sb --install-completion` will make TAB auto-complete automatically complete `sb` options for most platforms).  Installing auto-complete is **highly** recommended because it makes entering starbash commands fast by pressing the TAB key:

```
➜ pipx install starbash
  installed package starbash 0.1.3, installed using Python 3.12.3
  These apps are now globally available
    - sb
    - starbash
done! ✨ 🌟 ✨

➜ sb --install-completion
bash completion installed in /home/.../sb.sh
Completion will take effect once you restart the terminal

```

## Use

### Initial setup

The first time you launch starbash you will be prompted to choose a few options. You will also be told how you can add your existing raw frames and an input repo.

![user setup](doc/img/user-setup.png)

If you ever want to rerun this setup just run 'sb user setup'

### Automatic stacking/preprocessing

One of the main goals of starbash is to provide 'seestar-like' automatic image preprocessing:
* automatic stacking (even over multiple sessions) - (via Siril)
* automatic recipe selection (color, bw, duo filters etc...), but you can customize if starbash picks poorly
* background removal - (via Graxpert by default) provided as extra (optional) output files
* star removal - (via Starnet by default) provided as extra (optional) output files
* no changes to input repos - you can safely ask starbash to auto-process your entire tree of raw images.  Processed images go in a special 'processed' output repo.

![auto session](doc/vhs/process-auto.gif)

How to use:

* Step 1 - Select some sessions.  Example commands to use (when running commands the tool will provide feedback on what the current session set contains):

```
sb select any # selects all sessions in your repo
sb select # prints information about the current selection
sb select list # lists all sessions in the current selection
sb select date after 2025-09-01
sb select date before 2025-10-01
sb select date between 2025-07-03 2025-10-01

sb select target m31 # select all sessions with m31.
```
Note: Tab completion is supported so if you type select target m<tab>
you should get a list of all the Messier objects you have in your images.
In fact, tab completion works on virtually any starbash option - pressing
tab for dates will show you dates you have image sessions for instance...

* Step 2 - Generate 'master' images.  This will auto-stack your raw BIAS, DARK, FLAT etc... frames as single frame masters.  You only need to perform this step once:

```
sb process masters
```

* Step 3 - Do auto-process.  This will process all of the sessions you currently have selected.  It will group outputs by target name and it will auto-select flat frames on a per-session-date basis.  At the end of processing a list of targets and their processing will be printed.

```
sb process auto
```

The output directory (in addition to the processed fits outputs) will also contain a 'starbash.toml'.  That file contains information about what choices were made during processing (which masters selected, which recipes selected..., selected Siril options, etc...).

You can edit that file to pick different choices and if you reprocess that target your choices will be used.  (Note: this feature is not yet implemented in the release version of the tool - but soon.)

### Manual Siril processing

If you don't want the automated processing you can still ask Starbash to prepare a 'siril processing directory' with the appropriate flats, darks, biases and your light frames.  FIXME - add instructions on how to do this.

![siril session](doc/vhs/process-siril.gif)

## Supported commands

### Repository Management
- `sb repo list [--verbose]` - List installed repos (use `-v` for details)
- `sb repo add [--master] [filepath|URL]` - Add a repository, optionally specifying the type
- `sb repo remove <REPOURL>` - Remove the indicated repo from the repo list
- `sb repo reindex [--force] <REPOURL>` - Reindex the specified repo (or all repos if none specified)

### User Preferences
- `sb user name "Your Name"` - Set name for attribution in generated images
- `sb user email "foo@example.com"` - Set email for attribution in generated images
- `sb user analytics <on|off>` - Turn analytics collection on/off
- `sb user setup` - Configure starbash via a brief guided process

### Selection & Filtering
- `sb select` - Show information about the current selection
- `sb select list` - List sessions (filtered based on the current selection)
- `sb select any` - Remove all filters (select everything)
- `sb select target <TARGETNAME>` - Limit selection to the named target
- `sb select telescope <TELESCOPENAME>` - Limit selection to the named telescope
- `sb select date <after|before|between> <DATE> [DATE]` - Limit to sessions in the specified date range
- `sb select export SESSIONNUM DESTDIR` - Export the images for the indicated session number into the specified directory (or current directory if not specified).  If possible, symbolic links are used; if not, the files are copied.

### Selection information
- `sb info` - Show user preferences location and other app info
- `sb info target` - List targets (filtered based on the current selection)
- `sb info telescope` - List instruments (filtered based on the current selection)
- `sb info filter` - List all filters found in current selection
- `sb info master [KIND]` - List all precalculated master images (darks, biases, flats). Optional KIND argument to filter by image type (e.g., BIAS, DARK, FLAT).

## Not yet supported commands

### Export & Processing
- `sb process siril [--run] SESSIONNUM DESTDIR` - Generate Siril directory tree and optionally run Siril GUI.
- `sb process auto [SESSIONNUM]` - Automatic processing.  If session # is specified, process only that session; otherwise all selected sessions will be processed.
- `sb process masters` - Generate master flats, darks, and biases from available raw frames in the current selection.

## Supported telescope software

FIXME explain FITS and directory paths

* N.I.N.A. - tested, seems fairly okay.
* Asiair - tested, seems fairly okay.
* Seestar - tested, seems fairly okay.
* Ekos/Kstars - not tested; please try it and file a GitHub issue if you see any problems.

## Supported tools (now)

* Siril
* Graxpert
* Python (you can add Python code to recipes if necessary)

## Supported tools (future?)

* Pixinsight?
* Autostakkert?

## Development

We try to make this project useful and friendly.  If you find problems please file a GitHub issue.
We accept pull-requests and enjoy discussing possible new development directions via GitHub issues.  If you might want to work on this, just describe what your interests are and we can talk about how to get it merged.

[Click here](doc/development.md) for the current work in progress developer docs.  They will get better before our beta release...

## License

Copyright 2025 Kevin Hester, kevinh@geeksville.com.
Licensed under the [GPL v3](LICENSE)