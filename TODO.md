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
* [x] use recipe.priority to define recipe search order. lower pri searched first
* [x] figure out why devinit results in "HaOiii_Ha" in the filters table.  I _think_ this is harmless.  it is old processed files in from_asiair: "IC 1386/2025-09-01/results/bkg_result_Ha.fits"
* [x] make single duo work - need to write output files
* [x] make no/uni filter OSC work - selects wrong flat
* [x] make seestar IRCUT and LP filters work
* [x] check for BAYERPAT to find OSC cameras instead of require.camera
* [x] improve initial setup wizard - ask where to store masters and processed dirs
* [x] fix siril export
* [x] make a nicer movie, for setup and masters, auto, siril
* [x] update readme
* [x] ask Jaime to try it!
* [x] when processing masters always process entire repo
* [x] fix master processing result table display
* [x] organize bias/dark masters by camera ID not instrument ID (make an optional setting for this)
* [x] masters have to be organized by gain also
* [x] get_session_images is filtering out stacked biases - we don't want that, instead we want to let our regular fallback copy rule work for masters
* [x] when processing a target, generate a toml file with the options used to for that generation (so it can be regenerated or customized).  Include doc comments in that file for new users.
* [x] why are scores not being calculated?
* [x] masters have to be matched by gain (use in scoring)
* [x] require master-flats to come from the same instrument!
* [x] require biases/darks to come from the same camera!
* [x] penalize filter mismatch when doing flats
* [x] require masters dimensions match image dimensions for selection
* [x] let master generation work with only one input file (by copying)
* [x] look for STACKCNT in input images - if populated (i.e. in prestacked biases from another platform) that is a great indication it was a processed/stacked file
* [x] make score_candidates() highly prefer frames that are in the past. Better search by date for masters (i.e. must be in the past or near futurer)
* [x] fix remaining tool failures (just fail-ngc7023)

## First public alpha occured here

* [x] **first public alpha (reddit)** at approximately this point
* [ ] fix dwarf3 (bug #1) investigation by @codegistics
* [x] osx path finding fixes by @jmachuca77 (bug #2)
* [x] always regen masters after adding a repo
* [x] don't warn for "[tool-warnings] Reading sequence failed, file cannot be opened: *.seq. Reading sequence failed, file cannot be opened: *.seq." because harmless
* [x] add support for http URLs also.  use https://pypi.org/project/requests-cache/ and session = CachedSession(stale_if_error=True)
* [x] move the recipe repos to [their own github ](https://github.com/geeksville/starbash-recipes/)- stop pulling them as python resources
* [x] add dwarf3 files to integration tests - fix ghcr.io stuff
* [ ] explain about PATH https://github.com/geeksville/starbash/issues/5

(The following work items were all completed as part of the doit transition)
* [x] get the input files
* [x] get the output files
* [x] build and look at the list of doit tasks
* [x] populate the context
* [x] include target name in task names
* [x] fix multichannel input in osc
* [x] return real result codes from "process auto"
* [x] make single channel OSC work
* [x] share OSC code between dual duo and single channel OSC
* [x] create the ProcessedTarget by referring to the processed repo path info (need context first)
* [x] debug logs are busted!
* [x] fix Seestar m81 (no bias or flat cal frames)
* [x] why is process all not processing all?
* [x] m20 should pick dual duo but it isn't
* [x] store the various ScoredCandiates in the toml file (for considered masters) - use same convention as exluded scripts
* [x] Fix processing results display
* [x] m13 to work again
* [x] make integration test robust again
* [x] fix flats with new system
* [x] use user selected values from the toml file
* [x] try a test run on just a dual duo filter set
* [x] make master gen fully automatic as needed - hook together via dependencies
* [x] implement _filter_by_requires
* [x] change context["output"] to be a dataclass rather than a dict
* [x] use task name dependencies to join stages
* [x] try test run on the small dataset
* [x] move doit.db to app cache
* [x] test integration on big dataset
* [x] rexport the small test dataset (I've added a few files)
* [x] verify build takes zero time if no changes
* [x] scored candidates are no longer storing their confidence strings in the TOML!!!
* [x] ic434 dataset for dwarf3 is not generating flat masters

* [x] fix windows CI
* [x] allow toml target files to be customized
* [x] store flats in directory names based on INSTRUMENT not camera
* [x] Substantially improve progress display
* [x] "sb process masters" shows empty results list
* [ ] add parameterizations support

* [ ] do background_removal() as a separate stage via graxpert
* [ ] too many outputs from stacking job.
* [ ] graxpert needs to autodownload models
* [ ] graxpert needs to not add .fits suffix if the output file already has one

* [x] ask friends to send me the result of session list (with extra diagnostics turned on)
* [ ] generate an auto-stretched output as fits and jpg.
* [ ] make master-selection user customizable per target
* [ ] do auto star removal as a separate stage
* [ ] write a small tutorial/manual for recipes and parameters
* [x] add "darkorbias" as an input type.  make default recipes work with dark frames - not just bias frames - REQUIRED for dwarf3
* [x] make "repo list" only show user repos
* [x] cleanup how different stages dependencies work together: bug: see m31.  If a target has been taken by both seestar and nina, we pick an OSC recipe that then barfs because no bias-masters found for the seestar.  we should support mix-and match for recipe stages.  use the light frame stage for seestar but the final stack stage from osc?
* [x] too many cache dirs, delete after tasks
* [ ] improve user readability of process report files
* [ ] **second alpha release approximately here**

## Do second alpha here

* [ ] make graxpert network check faster & expose an API
* [ ] find a way to run the integration tests on a Windows VM (for #1 testing)
* [x] make test data even smaller
* [ ] merge Processing with ProcessingContext?
* [x] check for required/recommended tools at start.
* [x] for debugging purposes generate a mastername.sb.toml file per master - to see input selection choices
* [ ] include temperature in bias filenames.
* [ ] name the progess dirs so they can be semi-persistent (speed up reruns)
* [ ] let user spec a max cache size, if we exceed that just delete older build dirs from that cache as needed.  This would allow quick rebuilds for the last N targets rendered.
* [x] move processing code out of app
* [x] move masters code out of app
* [x] in osc processing implement make_renormalize()
* [x] make auto process work again for dual-duo single session workflows (test with NGC 281) sb.run_all_stages()
* [ ] master relative path should be based on unique camera ID - so that Ascar_V_80mm_flattener and Ascar_V_80mm_extender can share the same masters.
* [x] NotEnoughFilesError should not crash processing
* [ ] simple OSC processing scripts shouldn't even need custom python - make siril invoke smarter (by being multi-session aware for input files)
* [ ] find a way for scripts to share python code with each other
* [ ] implement recipe/repo inheritence to prevent the copypasta required in the existing OSC scripts
* [x] add progress 'spinner' bar while doing any tool runs... https://rich.readthedocs.io/en/latest/reference/spinner.html
* [x] return a list of ProcessingResult named tuples from auto and master processing.  print as table.
* [x] get a successful run on X
* [x] don't let logging mess up progress display when making masters https://rich.readthedocs.io/en/latest/progress.html#print-log
* [x] test missing siril/graxpert and helpful user message
* [x] fix "Registering and stacking 0 frames for SiiOiii/Ha"
* [x] make master dark/bias gen for asiair work
* [x] make process running smarter about printing messages as they occur
* [x] fix dark frame generation
* [x] make 'regen all masters' work
* [ ] normalize imagetyp before inserting them into session or images tables
* [ ] add backpointers to run-customization repo file to output FITS files.
* [ ] eventually store master info in the root toml file for masters
* [x] allow recipes to specify the min # of expected generated output files.  Currently we just assume it is 1
* [ ] more gracefully handle UnrecognizedAliasError and ask user if they want to add it...
* [ ] make output-path precheck work for "lights" rules so those expensive operations can sometimes be skipped
* [ ] make and intergration test that uses a few real files
* [ ] catch the exception for missing siril/graxpert and print user instructions on how to install
* [x] make flat rule work
* [ ] use normalized names when searching for filters or master or light frames
* [x] when reindexing/adding masters, put them in the session db as some sort of special entry
* [ ] make siril prep smarter about best sets, include report in toml file, show options on log
* [x] I bet that masters are probably being included in the session images, don't include them when passing image files to tasks.
* [ ] probably: instead of a list of repos we should keep repos in memory in a tree structure - which would allow walking up the tree to inherit/override entries.
* [x] add exposure length as another common element for a session
* [x] auto select workflows by filter name
* [x] make auto process work again for dual-duo _multi_ session workflows
* [x] add targets list
* [x] implement setup command (including username selection and analytics)
* [x] include instrument name in session list (for seestar,asiair,etc)
* [x] select default output should show summary info for current target & telescope.
* [x] REVLOCK the recipies repo so old builds keep working!
* [x] dependencies should auto skip rebuilds - though only within the 3 build cache limit
* [x] fix remaining failure in m20 target - the final stack_dual_duo is missing dependencies on the s35 prior stage outputs and has 2x dependencies on s36
* [ ] add graxpert
* [ ] change recipes to use imports
* [ ] cleanup Repo import code
* [ ] remove priorities from stages where dependencies should have worked.  hack to fix "Stages in priority order: ['stack_dual_duo', 'light', 'seqextract_haoiii'"
* [x] sort the masters list display
* [x] fix auto generation of processed directory paths
* [ ] track image quality on a per frame basis
* [x] use db find master bias frames
* [x] use db to find flat frames
* [x] use db to find light frames
* [x] add top level catch asking users to report bugs
* [x] add crash and usage analytics - sentry.io?
* [ ] move session config looping out of scripts - to require less script coding (Sii, Oiii etc...)
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
* [x] consider two different 'users' one who just wants to use the DB/repo stuff (doesn't need the auto processing) - for that user just let them do queries and build a 'process' directory for siril.  And the other user who wants our slick smart scripts to also do at least pre-processing.  In initial release just support the the query opts
* [ ] add makefile style dependencies
* [ ] allow selecting targets using OBJCTRA and OBJECTDEC + an angle of view - because it makes name differences meaningless.  possibly start with a name and then query a DB to find RA/DEC then look for the local images.
* [x] add FITS based filter detection (use astropy.io https://docs.astropy.org/en/stable/install.html)
* [x] make single DUO processing work
* [x] add a command to select the current set of sessions to process (allow filtering by target name, date, instrument, etc...)
* [x] have tab completion work for dates or target names (showing a shorthand of what the new selection would mean)
* [x] user https://typer.tiangolo.com/ for CLI support and rich-click
* [x] support subcommands per https://typer.tiangolo.com/tutorial/subcommands/add-typer/#put-them-together
* [x] support shell autocompletion on target names etc... https://typer.tiangolo.com/tutorial/options-autocompletion/#review-completion
* [x] add a command to list all known sessions in all repos (eventually use a DB to cache this info)
* [x] use https://tinydb.readthedocs.io as the DB?
* [x] render output (including tables) with https://github.com/Textualize/rich - use basic command lines at first
* [x] test on asiair, seestar, nina
* [ ] use get_safe more pervasively, pass in a help string to it (to indicate source of failure)
* [ ] remove nasty osc.py file - move into toml
* [ ] eventually do a simple gui using https://flet.dev/docs/
* [x] use import importlib.util to load python code it is own namespace
* [x] make crude flat frame generation work
* [x] make crude light frame processing work
* [x] normalize instrument names (removing spaces) when creating masters directories
* [x] don't include recipes in the list of repos on the CLI.
* [x] add a repo-add command that creates repo.sb.toml file in the rootdir and references it from users preferences.
* [x] have repo-add auto recognize common nina/asiair/seestar layouts
* [ ] generate a report on the final output including attribution for data sources, recpies etc...
* [x] make default invocation walk the user through creation of input and output repos.
* [ ] do star extraction
* [ ] don't regen masters/stacks/etc... if we don't need to - precheck for existence of output file
* [x] add a backpointer in stages to the recipe they came from (for attribution, reporting etc...)
* [ ] validate TOML files at load time to look for invalid keys (detect possible typos in recpie files etc...)
* [x] change from eval() to something more secure (ast + eval? a restricted dict API?)
* [x] add something like repo-add for masters and processed
* [ ] do background elim with graxpert (before?) tri merge
* [ ] have AI change asserts to raise ValueError (or something better?)
* [x] FIX GRAXPERT RELEASE
* [ ] add doit depenencies on the generated toml files
* [ ] add doit dependencies on the recipe files
* [ ] merge the tri colors into one file using pixel math
* [x] generalize processing to also work on single duo filter or broadband OSC
* [x] auto recognize my nina config, default nina config, asiair config, seestar config
* [x] list all found targets across all repos
* [x] allow restricting processing by date ranges, or equipment or whatever
* [ ] print report on frame quality, registration etc...
* [ ] get a real app icon (instead of current placeholder)
* [ ] experiment with auto generation of report text
* [ ] experiment with telescopus upload (filling in fields of image info with backpointers requesting feedback)
* [ ] make a "gen_test_db() function that can be used to generate either a huge or a tiny DB with 'real looking' test data (for performance tesing and CI).  Have it use a couple of real stripped FITS files.
