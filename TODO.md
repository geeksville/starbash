## TODO

* [x] FIX GRAXPERT AMD
* [x] unify the various processing routines by using a templating system
* [x] move the old processing stuff into the starbash namespace (run siril, etc...)
* [x] start writing user prefs in user prefs dir
* [x] make reindex smarter
* [x] make the various filter options work
* [x] apply filters to info commands
* [x] given a session, return a best set of flats or biases for that session (generalize later)
* [x] make the siril prep rule work
* [x] make master repo add work
* [x] make "session_to_master()" work - given a single session it will write masters/instrument/typ/foo-date-temp-bias.fits
* [x] clean up database abstraction and add repo table
* [x] auto provide bias frame to flat generation
* [x] make flat generation properly use session_config for filter name
* [x] when a new master is generated add it to the images table
* [x] make default repo paths work
* [x] make repo remove clean the db
* [x] require all images of a session to have the same exposure length see 2025-09-09 - it incorrectly only has one image in the session!
* [x] normalize session target names on insert, so that "sb select target m31" can work
* [x] handle "RuntimeError: Tool timed out after 60.0 seconds" gracefully
* [x] properly name target output dir
* [x] "HaOiii_Ha" should not appear in session list - exclude processed repos from session queries. It is in the from_asiair repourl though!
* [x] fix flat error msg when making masters
* [x] require biases built before flats
* [ ] master relative path should be based on unique camera ID - so that Ascar_V_80mm_flattener and Ascar_V_80mm_extender can share the same masters.
* [x] NotEnoughFilesError should not crash processing
* [ ] add progress 'spinner' bar while doing any tool runs... https://rich.readthedocs.io/en/latest/reference/spinner.html
* [ ] name the progess dirs so they can be semi-persistent
* [ ] get a successful run on X
* [x] don't let logging mess up progress display when making masters https://rich.readthedocs.io/en/latest/progress.html#print-log
* [ ] generate .toml in output processed dir
* [ ] share dual duo python with single duo python
* [ ] in osc processing implement make_renormalize() & background_removal()
* [ ] require masters dimensions match image dimensions for selection
* [ ] test missing siril/graxpert and helpful user message
* [ ] make auto process work again for dual-duo single session workflows (test with NGC 281) sb.run_all_stages()
* [x] fix "Registering and stacking 0 frames for SiiOiii/Ha"
* [x] make master dark/bias gen for asiair work
* [ ] include temperature in bias filenames.
* [x] make process running smarter about printing messages as they occur
* [x] fix dark frame generation
* [x] make 'regen all masters' work
* [ ] normalize imagetyp before inserting them into session or images tables
* [ ] add backpointers to run-customization repo file to output FITS files.
* [ ] eventually store master info in the root toml file for masters
* [ ] allow recipes to specify the min # of expected generated output files.  Currently we just assume it is 1
* [ ] gracefully handle UnrecognizedAliasError and ask user if they want to add it...
* [ ] make output-path precheck work for "lights" rules so those expensive operations can sometimes be skipped
* [ ] make score_candidates() highly prefer frames that are in the past
* [ ] make and intergration test that uses a few real files
* [ ] catch the exception for missing siril/graxpert and print user instructions
* [ ] always regen masters after adding a repo
* [x] make flat rule work
* [ ] use normalized names when searching for filters or master or light frames
* [x] when reindexing/adding masters, put them in the session db as some sort of special entry
* [ ] make siril prep smarter about best sets, include report in toml file, show options on log
* [ ] I bet that masters are probably being included in the session images, don't include them when passing image files to tasks.
* [ ] probably: instead of a list of repos we should keep repos in memory in a tree structure - which would allow walking up the tree to inherit/override entries.
* [x] add exposure length as another common element for a session
* [ ] validate resolution and binning when looking for darks etc...
* [ ] auto select workflows by filter name
* [ ] make auto process work again for dual-duo _multi_ session workflows
* [x] add targets list
* [x] implement setup command (including username selection and analytics)
* [ ] make a nicer movie
* [ ] ask friends to send me the result of session list (with extra diagnostics turned on)
* [x] include instrument name in session list (for seestar,asiair,etc)
* [ ] select default output should show summary info for current target & telescope.
* [ ] sort the masters list display
* [ ] fix auto generation of processed directory paths
* [ ] track image quality on a per frame basis
* [x] use db find master bias frames
* [ ] use db to find flat frames
* [x] use db to find light frames
* [x] add top level catch asking users to report bugs
* [x] add crash and usage analytics - sentry.io?
* [ ] add automated session config looping (Sii, Oiii etc...)
* [x] add automated session looping (multiday)
* [x] unify the script execution code between sessions and masters
* [x] pass stage outputs via the context?
* [ ] install bandit security tests https://bandit.readthedocs.io/en/latest/integrations.html
* [ ] generalize the various session selectors to make them just come from an array of column names (should allow removing the select telescope, select foo variants)
* [x] add the concept of filter aliases
* [ ] record # of repos, # of images, # of sessions, in analytics - to measure db sufficiency
* [x] does repo glob even matter if we just throw everything in the db based on fits metadata?  do an experiment.  YES it does, use DB based on FITS for all operations (instead of globs)
* [x] Add a db starbash.Database class, populated from repos.  Regen as needed.
* [x] change the info commands to use the current selection query (and include comparison to all in the output)
* [ ] Possibly store the DB queries as the description for the sesssion inputs?
* [ ] consider two different 'users' one who just wants to use the DB/repo stuff (doesn't need the auto processing) - for that user just let them do queries and build a 'process' directory for siril.  And the other user who wants our slick smart scripts to also do at least pre-processing.  In initial release just support the the query opts
* [ ] add support for http URLs also.  use https://pypi.org/project/requests-cache/ and session = CachedSession(stale_if_error=True)
* [ ] add makefile style dependencies
* [ ] allow selecting targets using OBJCTRA and OBJECTDEC + an angle of view - because it makes name differences meaningless.  possibly start with a name and then query a DB to find RA/DEC then look for the local images.
* [x] add FITS based filter detection (use astropy.io https://docs.astropy.org/en/stable/install.html)
* [ ] make single DUO processing work
* [x] add a command to select the current set of sessions to process (allow filtering by target name, date, instrument, etc...)
* [ ] keep quality metadata for every image that has been processed
* [x] have tab completion work for dates or target names (showing a shorthand of what the new selection would mean)
* [x] user https://typer.tiangolo.com/ for CLI support and rich-click
* [x] support subcommands per https://typer.tiangolo.com/tutorial/subcommands/add-typer/#put-them-together
* [x] support shell autocompletion on target names etc... https://typer.tiangolo.com/tutorial/options-autocompletion/#review-completion
* [x] add a command to list all known sessions in all repos (eventually use a DB to cache this info)
* [x] use https://tinydb.readthedocs.io as the DB?
* [x] render output (including tables) with https://github.com/Textualize/rich - use basic command lines at first
* [ ] test on asiair, seestar, nina
* [ ] eventually do a simple gui using https://flet.dev/docs/
* [ ] use import importlib.util to load python code it is own namespace
* [ ] make crude flat frame generation work
* [ ] make crude light frame processing work
* [ ] normalize instrument names (removing spaces) when creating masters directories
* [ ] don't include recipes in the list of repos on the CLI.
* [x] add a repo-add command that creates repo.sb.toml file in the rootdir and references it from users preferences.
* [ ] have repo-add auto recognize common nina/asiair/seestar layouts
* [ ] generate a report on the final output including attribution for data sources, recpies etc...
* [ ] when processing a target, generate a toml file with the options used to for that generation (so it can be regenerated or customized).  Include doc comments in that file for new users.
* [ ] make default invocation walk the user through creation of input and output repos.
* [ ] do star extraction
* [ ] don't regen masters/stacks/etc... if we don't need to - precheck for existence of output file
* [x] add a backpointer in stages to the recipe they came from (for attribution, reporting etc...)
* [ ] validate TOML files at load time to look for invalid keys (detect possible typos in recpie files etc...)
* [x] change from eval() to something more secure (ast + eval? a restricted dict API?)
* [ ] add something like repo-add for masters and processed
* [ ] do background elim with graxpert before tri merge
* [x] FIX GRAXPERT RELEASE
* [ ] merge the tri colors into one file using pixel math
* [x] generalize processing to also work on single duo filter or broadband OSC
* [ ] auto recognize my nina config, default nina config, asiair config, seestar config
* [ ] list all found targets across all repos
* [x] allow restricting processing by date ranges, or equipment or whatever
* [ ] print report on frame quality, registration etc...
* [ ] get a real app icon (instead of current placeholder)
* [ ] experiment with auto generation of report text
* [ ] experiment with telescopus upload (filling in fields of image info with backpointers requesting feedback)
* [ ] make a "gen_test_db() function that can be used to generate either a huge or a tiny DB with 'real looking' test data (for performance tesing and CI).  Have it use a couple of real stripped FITS files.
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
  -w, --outpipe              specify the path for the write pipe, a message is sent when siril is ready to receive commands
  -f, --format               print all supported image file formats (depending on installed libraries)
  -o, --offline              start in offline mode
  -v, --version              print the application’s version
  -c, --copyright            print the copyright
  --display=DISPLAY          X display to use

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