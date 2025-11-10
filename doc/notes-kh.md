# raw notes you probably don't care about

Unformatted 'notes to self' to the main dev...

## astrosnake ideas

Use https://siril.org/tutorials/bash-scripts/ for scripting externally? and or testing

## other apps

Someone just announced a closed source gui app with some similar features: https://www.reddit.com/r/AskAstrophotography/comments/1nkxud3/new_allinone_astro_imaging_app_live_stacking/

### Snakemake

snakemake vs doit.  Snakemake has wildcard support but is more complex.
tried it but way too complex for what I need



## interesting ai tools?

* [ ] expose this new thing via MCP or gemini extension?
* [ ] https://github.com/gemini-cli-extensions/nanobanana
* [ ] https://github.com/figma/figma-gemini-cli-extension


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