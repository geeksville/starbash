## TODO
This is a rough list of feature/bug workitems.  See headers below to see when particular features/fixes were added.

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
* [x] **first public alpha (reddit)** at approximately this point

### First public alpha (0.1.0) occured 2025/11/11 ish

Changes since alpha 1...

* [x] bug #1 - fix dwarf3 investigation by @codegistics (probably fixed?)
* [x] bug #2 - osx path finding fixes by @jmachuca77
* [x] always regen masters after adding a repo
* [x] don't warn for "[tool-warnings] Reading sequence failed, file cannot be opened: *.seq. Reading sequence failed, file cannot be opened: *.seq." because harmless
* [x] add support for http URLs also.  use https://pypi.org/project/requests-cache/ and session = CachedSession(stale_if_error=True)
* [x] move the recipe repos to [their own github ](https://github.com/geeksville/starbash-recipes/)- stop pulling them as python resources
* [x] add dwarf3 files to integration tests - fix ghcr.io stuff
* [x] explain about PATH https://github.com/geeksville/starbash/issues/5
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
* [x] do background_removal() as a separate stage via graxpert
* [x] too many outputs from stacking job.
* [x] remove 2 second pause in graxpert launch
* [x] graxpert needs to autodownload models
* [x] graxpert needs to not add .fits suffix if the output file already has one
* [x] auto determine graxpert script input arguments
* [x] with latest changes 'seqextract_haoiii_m20_s41' (and later stages) is not finding correct input dependencies - should be dependant on prior stage outputs
* [x] cope with multiple inputs to graxpert background elim
* [x] auto generate outout names based on input names (see background.toml)
* [x] pass in model options to graxpert
* [x] why was stack_osc_m20 and stack_dual_duo_m20 both allowed to run? NOT a bug, because they generate different non-conflicting output names.  if user wants they can manually exclude certain stages
* [x] make graxpert network check faster & expose a graxpert API
* [x] add graxpert noise and deconv steps
* [x] do new graxpert release v3.2.0a1
* [x] make integration-test work again (m13, possibly a problem with auto master generation?)
* [x] skip graxpert denoise by default (it is very slow)
* [x] push to main and bump to 0.1.29 on pypi
* [x] don't spam warnings when no internet connection
* [x] bug: dies due to differing resolutions in merge. can repo with m31 test set - https://github.com/geeksville/starbash/issues/9
* [x] test case m20 failing due to two tasks targeting stacked_Ha.fits
* [x] test and adjust (m31?) multisession/mixed device stacking
* [x] store siril/graxpert/anytool logs in the output directory...
* [x] ic test failing on ic434 - make auto master processing smarter - this will fix the integration test
* [x] fix: getting removed in preflight because stage exclusions need to be session specific
* [x] while developing default to pulling recipes from local submodule
* [x] add parameterizations support - so scripts can have named preferences that get stored in toml run file - use for graxpert smoothing etc...
* [x] show only first 5 and last 10 lines for siril failures
* [x] bug: ngc6888 (in the big test data set) needs looser registration requirements
* [x] include siril author credits
* [x] Anonymize SITELONG and SITELAT in output files, to prevent users from accidentally leaking PII
* [x] split out most of osc.py?
* [x] input_files should be cleared from imported contexts.
* [x] ask friends to send me the result of session list (with extra diagnostics turned on)
* [x] provide link to generated starbash.toml files
* [x] generate an auto-stretched output as jpg thumbnails.
* [x] make master-selection user customizable per target
* [x] ping current users / other devs for new feedback
* [x] add "darkorbias" as an input type.  make default recipes work with dark frames - not just bias frames - REQUIRED for dwarf3
* [x] make "repo list" only show user repos
* [x] cleanup how different stages dependencies work together: bug: see m31.  If a target has been taken by both seestar and nina, we pick an OSC recipe that then barfs because no bias-masters found for the seestar.  we should support mix-and match for recipe stages.  use the light frame stage for seestar but the final stack stage from osc?
* [x] too many cache dirs, delete after tasks
* [x] no need for a cheaper modification checker - current checker only uses the expensive md5 if the file timestamp differs and the size has not changed.  But if that is too expensive TimestampChecker is available.
* [x] include thanks for siril,graxpert,starnet,doit
* [x] improve user readability of process report files
* [x] make a use_drizzle prefs option, make it work on a per project or per user basis (drizzle uses LOTS of disk space)
* [x] confirm that a virgin install gives a good error message for "sb process auto"
* [x] resolve remaing README FIXMEs
* [x] **second alpha release approximately here**

### Do second alpha (0.2.0) here

Changes after alpha 2... (not yet prioritized, need to schedule for about a month later, mostly driven by user reports/analytics...)

* [ ] include some example thumbnails in the README.
* [ ] improve code coverage tests by making a micro FITS test files that do at least one full autoprocess, this will get us coverage on essentially all remaining lines.
* [ ] include the session query expression in the report toml, so that any regens of the same folder keep those same settings (until changed)
* [-] NOT NEEDED: exclude_by_default works better for this application. change "exclude_by_default" to use the new parameters system instead.
* [ ] do the auto star removal as a separate stage
* [ ] don't show source files in log view when running a non developer build?
* [ ] use pixelmath to merge multichannel output files into a single file
* [ ] compare one of my duo duo test cases 'hand workflow' to the automated result
* [ ] talk with Siril devs about "merge" improvements, possibly make and send in a PR
* [ ] easy picker UI so users can set aliases or change master/exclusion settings without editing toml files
* [ ] add initial IPFS support (via a new tool subclass?)
* [ ] experiment with telescopus tool (filling in fields of image info with backpointers requesting feedback)
* [ ] add warning about trusting recipe sources, because recipes can contain python code.
* [ ] write a small tutorial/manual for recipes and parameters - explain make philosophy, reusability rather than brittlness, agnostic engine, sharability/tracability
* [ ] pull pixelmathish things etc... into small post-stack stages
* [ ] disabled overrides spam extra comments to starbash.toml, fix that by using "overrides_disabled"?
* [ ] experiment with parallel task execution: https://github.com/pydoit/doit/blob/00c136f5dfe7e9039d0fed6dddd6d45c84c307b4/doc/cmd-run.rst#parallel-execution.  Though locks would need around final run logging
* [ ] use caching fetch to speed up graxpert downloads
* [ ] find a way to run the integration tests on a Windows VM (for #1 testing)
* [x] make test data even smaller
* [x] merge Processing with ProcessingContext?
* [x] check for required/recommended tools at start.
* [x] for debugging purposes generate a mastername.sb.toml file per master - to see input selection choices
* [ ] include temperature in bias filenames.
* [ ] Possibly package as a Siril extension (might need to send in PRs for Siril?) to give Siril built in multisession/sharable recipes support?
* [x] name the progess dirs so they can be semi-persistent (speed up reruns)
* [ ] let user spec a max cache size, if we exceed that just delete older build dirs from that cache as needed.  This would allow quick rebuilds for the last N targets rendered.
* [x] move processing code out of app
* [x] move masters code out of app
* [x] in osc processing implement make_renormalize()
* [x] make auto process work again for dual-duo single session workflows (test with NGC 281) sb.run_all_stages()
* [ ] master relative path should be based on unique camera ID - so that Ascar_V_80mm_flattener and Ascar_V_80mm_extender can share the same masters.
* [x] NotEnoughFilesError should not crash processing
* [x] simple OSC processing scripts shouldn't even need custom python - make siril invoke smarter (by being multi-session aware for input files)
* [ ] find a way for scripts to share python code with each other
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
* [x] add backpointers to run-customization repo file to output FITS files.
* [x] eventually store master info in the root toml file for masters
* [x] allow recipes to specify the min # of expected generated output files.  Currently we just assume it is 1
* [ ] more gracefully handle UnrecognizedAliasError and ask user if they want to add it...
* [x] make output-path precheck work for "lights" rules so those expensive operations can sometimes be skipped
* [x] make and intergration test that uses a few real files
* [ ] make UserHandledError actually prompt for a user decision (aliases etc...)
* [x] make flat rule work
* [x] use normalized names when searching for filters or master or light frames
* [x] when reindexing/adding masters, put them in the session db as some sort of special entry
* [x] make siril prep smarter about best sets, include report in toml file, show options on log
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
* [x] add graxpert
* [ ] implement recipe/repo inheritence to prevent the copypasta required in the existing OSC scripts
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
* [x] move session config looping out of scripts - to require less script coding (Sii, Oiii etc...)
* [x] add automated session looping (multiday)
* [x] unify the script execution code between sessions and masters
* [x] pass stage outputs via the context?
* [x] FIX GRAXPERT RELEASE
* [x] generalize the various session selectors to make them just come from an array of column names (should allow removing the select telescope, select foo variants)
* [x] add the concept of filter aliases
* [ ] record # of repos, # of images, # of sessions, in analytics - to measure db sufficiency
* [x] does repo glob even matter if we just throw everything in the db based on fits metadata?  do an experiment.  YES it does, use DB based on FITS for all operations (instead of globs)
* [x] Add a db starbash.Database class, populated from repos.  Regen as needed.
* [x] change the info commands to use the current selection query (and include comparison to all in the output)
* [x] consider two different 'users' one who just wants to use the DB/repo stuff (doesn't need the auto processing) - for that user just let them do queries and build a 'process' directory for siril.  And the other user who wants our slick smart scripts to also do at least pre-processing.  In initial release just support the the query opts
* [x] add makefile style dependencies
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
* [x] use import importlib.util to load python code it is own namespace
* [x] make crude flat frame generation work
* [x] make crude light frame processing work
* [x] normalize instrument names (removing spaces) when creating masters directories
* [x] don't include recipes in the list of repos on the CLI.
* [x] add a repo-add command that creates repo.sb.toml file in the rootdir and references it from users preferences.
* [x] have repo-add auto recognize common nina/asiair/seestar layouts
* [ ] generate a report on the final output including attribution for data sources, recipes etc...
* [x] make default invocation walk the user through creation of input and output repos.
* [x] don't regen masters/stacks/etc... if we don't need to - precheck for existence of output file
* [x] add a backpointer in stages to the recipe they came from (for attribution, reporting etc...)

* [x] change from eval() to something more secure (ast + eval? a restricted dict API?)
* [x] add something like repo-add for masters and processed
* [ ] do background elim with graxpert (before?) tri merge
* [ ] mass-change all asserts to raise ValueError instead (or something better?)

* [ ] add doit depenencies on the generated toml files
* [ ] add doit dependencies on the recipe files
* [x] generalize processing to also work on single duo filter or broadband OSC
* [x] auto recognize my nina config, default nina config, asiair config, seestar config
* [x] list all found targets across all repos
* [x] allow restricting processing by date ranges, or equipment or whatever
* [ ] print report on frame quality, registration etc...
* [ ] get a real app icon (instead of current placeholder)
* [ ] experiment with auto generation of report text

* [ ] make python more secure/restrictive.  Currently recipes are running general python code that can do anything.
* [ ] install bandit security tests https://bandit.readthedocs.io/en/latest/integrations.html
* [ ] allow selecting targets using OBJCTRA and OBJECTDEC + an angle of view - because it makes name differences meaningless.  possibly start with a name and then query a DB to find RA/DEC then look for the local images.
* [ ] Possibly store the DB queries as the description for the sesssion inputs?
* [ ] eventually do a simple gui using https://flet.dev/docs/
* [ ] validate TOML files at load time to look for invalid keys (detect possible typos in recipe files etc...)
* [ ] make a "gen_test_db() function that can be used to generate either a huge or a tiny DB with 'real looking' test data (for performance tesing and CI).  Have it use a couple of real stripped FITS files.

## Textual work items

Alas Textual died as a company earlier this year https://textual.textualize.io/blog/2025/05/07/the-future-of-textualize/

ui/alias_editor.py - shows an editor pane for user repo.aliases. using
toml_table_editor: allows adding new keys.  existing table is listed 'tree style'
include a raw editor based on TextArea

* make a TomlEditor widget - initially based on TextArea, but eventually some sort of tree view.  Have it be "reactive" https://textual.textualize.io/tutorial/ to auto update the view when the config changes (i.e. as a run progresses)

* TaskListView: make a reactive Task watcher view that watches a list of Tasks and updates as the build progresses
Initially use https://textual.textualize.io/guide/reactivity/#recompose when we see tasks change.

* Normal app layout is a big LogView on the right and a TaskView on the left.  After completion a ResultsListView will show list of results.

* A ResultView includes an "edit config" button to open the TargetEditor beneath the ResultView (to edit the toml).  Or possibly make a new "Screen" for that https://textual.textualize.io/guide/screens/#screen-stack

Initially enable borders and border titles on all widgets: https://textual.textualize.io/guide/widgets/#border-titles

Example of usign a rich table: https://textual.textualize.io/guide/widgets/#rich-renderables

Using a 'loading indicator' for not yet ready views (not completed tasks?  once task is completed show the command output from that task): https://textual.textualize.io/guide/widgets/#loading-indicator

Possibly use https://textual.textualize.io/guide/screens/#modal-screens to make a pop-up picker view for used/excluded or masters?  But probably better as: https://textual.textualize.io/widget_gallery/#optionlist

Eventually use this for log view? https://textual.textualize.io/guide/widgets/#render-line-method

Possibly have a "Settings screen" a "Processing screen" and a "Target editor" screen? https://textual.textualize.io/guide/screens/#modes.  But probably better to do this instead: https://textual.textualize.io/widget_gallery/#tabbedcontent

Use a worker thread to run the "processing task" https://textual.textualize.io/guide/workers/#thread-workers

Use the command pallet for all user commands: https://textual.textualize.io/guide/command_palette/#launching-the-command-palette

How to test: https://textual.textualize.io/guide/testing/

Possibly run textual in a web browser: https://github.com/Textualize/textual-serve

Use something inspired by https://textual.textualize.io/api/logging/ for logging but different, because we need those logs to go in a queue for a custom widget intead...
Use this to implement: https://textual.textualize.io/widget_gallery/#richlog

### tutorial

Good referance: https://textual.textualize.io/guide/app/
* Set a title/subtitle: https://textual.textualize.io/guide/app/#title-and-subtitle
* Layouts of containers: https://textual.textualize.io/guide/layout/#composing-with-context-managers

"textual[syntax]"

see demo with

python -m textual