## TODO

* !FIX GRAXPERT AMD
* !unify the various processing routines by using a templating system
* !move the old processing stuff into the astroglue namespace (run siril, etc...)
* add automated session config looping (Sii, Oiii etc...)
* add automated session looping (multiday)
* add makefile style dependencies
* add FITS based filter detection
* make single DUO processing work
* add a command to select the current set of sessions to process (allow filtering by target name, date, instrument, etc...)
* add a command to list all known sessions in all repos (eventually use a DB to cache this info)
* use https://tinydb.readthedocs.io as the DB?
* render output (including tables) with https://github.com/Textualize/rich - use basic command lines at first
* eventually do a simple gui using https://flet.dev/docs/
* use import importlib.util to load python code it is own namespace
* make crude flat frame generation work
* make crude light frame processing work
* use repo globs to find master bias frames
* use repo globs to find flat frames
* use repo globs to find light frames
* add a repo-add command that creates repo.ag.toml file in the rootdir and references it from users preferences.
* have repo-add auto recognize common nina/asiair/seestar layouts
* generate a report on the final output including attribution for data sources, recpies etc...
* do star extraction
* don't regen masters/stacks/etc... if we don't need to - precheck for existence of output file
* add a backpointer in stages to the recipe they came from (for attribution, reporting etc...)
* validate TOML files at load time to look for invalid keys (detect possible typos in recpie files etc...)
* make generalized (not just file) URLs work for repos etc...
* change from eval() to something more secure (ast + eval? a restricted dict API?)
* add something like repo-add for masters and processed
* do background elim with graxpert before tri merge
* !FIX GRAXPERT RELEASE
* merge the tri colors into one file using pixel math
* !generalize processing to also work on single duo filter or broadband OSC
* auto recognize my nina config, default nina config, asiair config, seestar config
* list all found targets across all repos
* allow restricting processing by date ranges, or equipment or whatever
* print report on frame quality, registration etc...

## astrosnake ideas

Use https://siril.org/tutorials/bash-scripts/ for scripting externally? and or testing

## other apps

Someone just announced a closed source gui app with some similar features: https://www.reddit.com/r/AskAstrophotography/comments/1nkxud3/new_allinone_astro_imaging_app_live_stacking/

### Snakemake

snakemake vs doit.  Snakemake has wildcard support but is more complex.
tried it but way too complex for what I need

## runing siril

(snakemake) vscode ➜ ~ $ org.siril.Siril --help
Usage:
  siril [OPTION…]

Siril - A free astronomical image processing software.

Help Options:
  -h, --help                 Show help options
  --help-all                 Show all help options
  --help-gapplication        Show GApplication options
  --help-gtk                 Show GTK+ Options

Application Options:
  -d, --directory            changing the current working directory as the argument
  -s, --script               run the siril commands script in console mode. If argument is equal to "-", then siril will read stdin input
  -i, --initfile             load configuration from file name instead of the default configuration file
  -p, --pipe                 run in console mode with command and log stream through named pipes
  -r, --inpipe               specify the path for the read pipe, the one receiving commands
  -w, --outpipe              specify the path for the write pipe, the one outputting messages
  -f, --format               print all supported image file formats (depending on installed libraries)
  -o, --offline              start in offline mode
  -v, --version              print the application’s version
  -c, --copyright            print the copyright
  --display=DISPLAY          X display to use

## interesting ai tools?

* expose this new thing via MCP or gemini extension?
* https://github.com/gemini-cli-extensions/nanobanana
* https://github.com/figma/figma-gemini-cli-extension