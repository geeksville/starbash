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
* [ ] bug: dies due to differing resolutions in merge. can repo with m31 test set - https://github.com/geeksville/starbash/issues/9
* [x] test case m20 failing due to two tasks targeting stacked_Ha.fits
* [ ] ic test failing on ic434 - make auto master processing smarter
* [x] fix: getting removed in preflight because stage exclusions need to be session specific
* [x] while developing default to pulling recipes from local submodule
* [ ] automatically do process masters before first run?
* [x] add parameterizations support - so scripts can have named preferences that get stored in toml run file - use for graxpert smoothing etc...
* [ ] use pixelmath to merge multichannel output files into a single file
* [ ] split out most of osc.py?
* [x] input_files should be cleared from imported contexts.  To fix:

* [x] ask friends to send me the result of session list (with extra diagnostics turned on)
* [ ] provide link to generated starbash.toml files
* [x] generate an auto-stretched output as jpg thumbnails.
* [x] make master-selection user customizable per target
* [ ] do auto star removal as a separate stage
* [ ] write a small tutorial/manual for recipes and parameters - explain make philosophy, reusability rather than brittlness, agnostic engine, sharability/tracability
* [x] add "darkorbias" as an input type.  make default recipes work with dark frames - not just bias frames - REQUIRED for dwarf3
* [x] make "repo list" only show user repos
* [x] cleanup how different stages dependencies work together: bug: see m31.  If a target has been taken by both seestar and nina, we pick an OSC recipe that then barfs because no bias-masters found for the seestar.  we should support mix-and match for recipe stages.  use the light frame stage for seestar but the final stack stage from osc?
* [x] too many cache dirs, delete after tasks
* [ ] improve user readability of process report files
* [ ] **second alpha release approximately here**

## Do second alpha here

* [ ] use caching fetch to speed up graxpert downloads
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
* [x] add graxpert
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

List of currently failing runs:



                                   Autoprocessed to /workspaces/starbash/images/processed
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Target          ┃                          Session ┃  Status   ┃ Notes                                                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ic1848          │  2025-09-07:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s63 → bkg_pp_light_s63_.seq        │
│ ic1848          │ 2025-09-12:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s72 → bkg_pp_light_s72_.seq        │
│ ic1848          │  2025-09-06:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s60 → bkg_pp_light_s60_.seq        │
│ ic1848          │  2025-09-15:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s76 → bkg_pp_light_s76_.seq        │
│ ic1848          │ 2025-09-14:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s74 → bkg_pp_light_s74_.seq        │
│ ic1848          │  2025-09-08:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s68 → bkg_pp_light_s68_.seq        │
│ ic1848          │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ic1848_s78 → bkg_pp_light_s78_.seq        │
│ ic1848          │  2025-09-07:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s63 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s63_.seq, OIII_bkg_pp_light_s63_.seq    │
│ ic1848          │ 2025-09-12:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s72 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s72_.seq, OIII_bkg_pp_light_s72_.seq    │
│ ic1848          │  2025-09-06:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s60 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s60_.seq, OIII_bkg_pp_light_s60_.seq    │
│ ic1848          │  2025-09-15:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s76 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s76_.seq, OIII_bkg_pp_light_s76_.seq    │
│ ic1848          │ 2025-09-14:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s74 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s74_.seq, OIII_bkg_pp_light_s74_.seq    │
│ ic1848          │  2025-09-08:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s68 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s68_.seq, OIII_bkg_pp_light_s68_.seq    │
│ ic1848          │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1848_s78 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s78_.seq, OIII_bkg_pp_light_s78_.seq    │
│ ic1848          │ 2025-09-16:light_SiiOiii_gain100 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/ic1848 -s -'    │
│                 │                                  │           │ failed                                                  │
│ sadr            │       2025-07-15:light_LP_gain80 │ ✓ Success │ light_no_darks_sadr_s48 → bkg_pp_light_s48_.seq         │
│ sadr            │       2025-07-15:light_LP_gain80 │ ✓ Success │ stack_osc_sadr → stacked.fits                           │
│ sadr            │       2025-07-15:light_LP_gain80 │ ✓ Success │ background_sadr_i0 → bk_stacked.fits                    │
│ andromedagalaxy │    2025-09-01:light_None_gain100 │ ✓ Success │ light_vs_dark_andromedagalaxy_s139 →                    │
│                 │                                  │           │ bkg_pp_light_s139_.seq                                  │
│ andromedagalaxy │    2025-09-01:light_None_gain100 │ ✓ Success │ stack_osc_andromedagalaxy → stacked.fits                │
│ andromedagalaxy │    2025-09-01:light_None_gain100 │ ✓ Success │ background_andromedagalaxy_i0 → bk_stacked.fits         │
│ m27             │       2025-07-10:light_LP_gain80 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/m27 -s -'       │
│                 │                                  │           │ failed                                                  │
│ m51             │    2025-07-03:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m51_s36 → bkg_pp_light_s36_.seq          │
│ m51             │    2025-07-08:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m51_s38 → bkg_pp_light_s38_.seq          │
│ m51             │    2025-07-13:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m51_s35 → bkg_pp_light_s35_.seq          │
│ m51             │    2025-07-11:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m51_s37 → bkg_pp_light_s37_.seq          │
│ m51             │    2025-07-08:light_IRCUT_gain80 │ ✓ Success │ stack_osc_m51 → stacked.fits                            │
│ m51             │    2025-07-08:light_IRCUT_gain80 │ ✓ Success │ background_m51_i0 → bk_stacked.fits                     │
│ m100            │    2025-07-07:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m100_s22 → bkg_pp_light_s22_.seq         │
│ m100            │    2025-07-04:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m100_s21 → bkg_pp_light_s21_.seq         │
│ m100            │    2025-07-15:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m100_s23 → bkg_pp_light_s23_.seq         │
│ m100            │    2025-07-15:light_IRCUT_gain80 │ ✓ Success │ stack_osc_m100 → stacked.fits                           │
│ m100            │    2025-07-15:light_IRCUT_gain80 │ ✓ Success │ background_m100_i0 → bk_stacked.fits                    │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic5146_s81 → bkg_pp_light_s81_.seq        │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ stack_osc_ic5146 → stacked.fits                         │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic5146_s81 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s81_.seq, OIII_bkg_pp_light_s81_.seq    │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_ic5146_i2 → bk_stacked.fits                  │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ stack_single_duo_ic5146 → stacked_Ha.fits,              │
│                 │                                  │           │ stacked_OIII.fits                                       │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_ic5146_i0 → bk_stacked_Ha.fits               │
│ ic5146          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_ic5146_i1 → bk_stacked_OIII.fits             │
│ ngc6888         │       2025-07-07:light_LP_gain80 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/ngc6888 -s -'   │
│                 │                                  │           │ failed                                                  │
│ m81             │    2025-07-14:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m81_s39 → bkg_pp_light_s39_.seq          │
│ m81             │    2025-07-14:light_IRCUT_gain80 │ ✓ Success │ stack_osc_m81 → stacked.fits                            │
│ m81             │    2025-07-14:light_IRCUT_gain80 │ ✓ Success │ background_m81_i0 → bk_stacked.fits                     │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_lbn354_s86 → bkg_pp_light_s86_.seq        │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_lbn354_s86 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s86_.seq, OIII_bkg_pp_light_s86_.seq    │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ stack_osc_lbn354 → stacked.fits                         │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ stack_single_duo_lbn354 → stacked_Ha.fits,              │
│                 │                                  │           │ stacked_OIII.fits                                       │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_lbn354_i2 → bk_stacked.fits                  │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_lbn354_i0 → bk_stacked_Ha.fits               │
│ lbn354          │  2025-09-03:light_HaOiii_gain100 │ ✓ Success │ background_lbn354_i1 → bk_stacked_OIII.fits             │
│ ic1396          │  2025-09-02:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ic1396_s52 → bkg_pp_light_s52_.seq        │
│ ic1396          │  2025-09-02:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ic1396_s52 →                          │
│                 │                                  │           │ Ha_bkg_pp_light_s52_.seq, OIII_bkg_pp_light_s52_.seq    │
│ ic1396          │  2025-09-02:light_HaOiii_gain100 │ ✗ Failed  │ Error during python script execution                    │
│ pinwheelgalaxy  │    2025-09-01:light_None_gain100 │ ✓ Success │ light_vs_dark_pinwheelgalaxy_s138 →                     │
│                 │                                  │           │ bkg_pp_light_s138_.seq                                  │
│ pinwheelgalaxy  │    2025-09-01:light_None_gain100 │ ✓ Success │ stack_osc_pinwheelgalaxy → stacked.fits                 │
│ pinwheelgalaxy  │    2025-09-01:light_None_gain100 │ ✓ Success │ background_pinwheelgalaxy_i0 → bk_stacked.fits          │
│ ic5070          │       2025-07-04:light_LP_gain80 │ ✓ Success │ light_no_darks_ic5070_s20 → bkg_pp_light_s20_.seq       │
│ ic5070          │       2025-07-04:light_LP_gain80 │ ✓ Success │ stack_osc_ic5070 → stacked.fits                         │
│ ic5070          │       2025-07-04:light_LP_gain80 │ ✓ Success │ background_ic5070_i0 → bk_stacked.fits                  │
│ ngc6960         │    2025-07-28:light_HaO3_gain100 │ ✓ Success │ light_vs_dark_ngc6960_s5 → bkg_pp_light_s5_.seq         │
│ ngc6960         │    2025-07-28:light_HaO3_gain100 │ ✓ Success │ seqextract_haoiii_ngc6960_s5 → Ha_bkg_pp_light_s5_.seq, │
│                 │                                  │           │ OIII_bkg_pp_light_s5_.seq                               │
│ ngc6960         │       2025-07-17:light_LP_gain80 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/ngc6960 -s -'   │
│                 │                                  │           │ failed                                                  │
│ ngc7635         │  2025-09-20:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s122 → bkg_pp_light_s122_.seq     │
│ ngc7635         │  2025-09-21:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s127 → bkg_pp_light_s127_.seq     │
│ ngc7635         │ 2025-09-20:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s123 → bkg_pp_light_s123_.seq     │
│ ngc7635         │  2025-09-23:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s130 → bkg_pp_light_s130_.seq     │
│ ngc7635         │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s131 → bkg_pp_light_s131_.seq     │
│ ngc7635         │ 2025-09-21:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7635_s126 → bkg_pp_light_s126_.seq     │
│ ngc7635         │  2025-09-20:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s122 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s122_.seq, OIII_bkg_pp_light_s122_.seq  │
│ ngc7635         │  2025-09-21:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s127 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s127_.seq, OIII_bkg_pp_light_s127_.seq  │
│ ngc7635         │ 2025-09-20:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s123 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s123_.seq, OIII_bkg_pp_light_s123_.seq  │
│ ngc7635         │  2025-09-23:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s130 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s130_.seq, OIII_bkg_pp_light_s130_.seq  │
│ ngc7635         │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s131 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s131_.seq, OIII_bkg_pp_light_s131_.seq  │
│ ngc7635         │ 2025-09-21:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7635_s126 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s126_.seq, OIII_bkg_pp_light_s126_.seq  │
│ ngc7635         │ 2025-09-23:light_SiiOiii_gain100 │ ✗ Failed  │ Error during python script execution                    │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc281_s110 → bkg_pp_light_s110_.seq      │
│ ngc281          │  2025-09-17:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ngc281_s109 → bkg_pp_light_s109_.seq      │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc281_s110 →                         │
│                 │                                  │           │ Ha_bkg_pp_light_s110_.seq, OIII_bkg_pp_light_s110_.seq  │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ stack_osc_ngc281 → stacked.fits                         │
│ ngc281          │  2025-09-17:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc281_s109 →                         │
│                 │                                  │           │ Ha_bkg_pp_light_s109_.seq, OIII_bkg_pp_light_s109_.seq  │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ background_ngc281_i3 → bk_stacked.fits                  │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ stack_dual_duo_ngc281 → stacked_Ha.fits,                │
│                 │                                  │           │ stacked_OIII.fits, stacked_Sii.fits                     │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ background_ngc281_i1 → bk_stacked_OIII.fits             │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ background_ngc281_i0 → bk_stacked_Ha.fits               │
│ ngc281          │ 2025-09-17:light_SiiOiii_gain100 │ ✓ Success │ background_ngc281_i2 → bk_stacked_Sii.fits              │
│ m45             │    2025-09-16:light_None_gain100 │ ✓ Success │ light_vs_dark_m45_s106 → bkg_pp_light_s106_.seq         │
│ m45             │    2025-09-16:light_None_gain100 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/m45 -s -'       │
│                 │                                  │           │ failed                                                  │
│ m13             │    2025-08-25:light_None_gain100 │ ✓ Success │ light_vs_dark_m13_s3 → bkg_pp_light_s3_.seq             │
│ m13             │    2025-07-12:light_IRCUT_gain80 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/m13 -s -'       │
│                 │                                  │           │ failed                                                  │
│ ngc6939         │    2025-08-25:light_None_gain100 │ ✓ Success │ light_vs_dark_ngc6939_s4 → bkg_pp_light_s4_.seq         │
│ ngc6939         │    2025-08-25:light_None_gain100 │ ✓ Success │ stack_osc_ngc6939 → stacked.fits                        │
│ ngc6939         │    2025-08-25:light_None_gain100 │ ✓ Success │ background_ngc6939_i0 → bk_stacked.fits                 │
│ ngc7000         │  2025-09-15:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7000_s117 → bkg_pp_light_s117_.seq     │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7000_s119 → bkg_pp_light_s119_.seq     │
│ ngc7000         │ 2025-09-14:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_ngc7000_s115 → bkg_pp_light_s115_.seq     │
│ ngc7000         │  2025-09-15:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7000_s117 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s117_.seq, OIII_bkg_pp_light_s117_.seq  │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7000_s119 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s119_.seq, OIII_bkg_pp_light_s119_.seq  │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ stack_osc_ngc7000 → stacked.fits                        │
│ ngc7000         │ 2025-09-14:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_ngc7000_s115 →                        │
│                 │                                  │           │ Ha_bkg_pp_light_s115_.seq, OIII_bkg_pp_light_s115_.seq  │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ background_ngc7000_i3 → bk_stacked.fits                 │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ stack_dual_duo_ngc7000 → stacked_Ha.fits,               │
│                 │                                  │           │ stacked_OIII.fits, stacked_Sii.fits                     │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ background_ngc7000_i1 → bk_stacked_OIII.fits            │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ background_ngc7000_i2 → bk_stacked_Sii.fits             │
│ ngc7000         │ 2025-09-16:light_SiiOiii_gain100 │ ✓ Success │ background_ngc7000_i0 → bk_stacked_Ha.fits              │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ light_vs_dark_m20_s92 → bkg_pp_light_s92_.seq           │
│ m20             │  2025-09-23:light_HaOiii_gain100 │ ✓ Success │ light_vs_dark_m20_s91 → bkg_pp_light_s91_.seq           │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ seqextract_haoiii_m20_s92 → Ha_bkg_pp_light_s92_.seq,   │
│                 │                                  │           │ OIII_bkg_pp_light_s92_.seq                              │
│ m20             │  2025-09-23:light_HaOiii_gain100 │ ✓ Success │ seqextract_haoiii_m20_s91 → Ha_bkg_pp_light_s91_.seq,   │
│                 │                                  │           │ OIII_bkg_pp_light_s91_.seq                              │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ stack_osc_m20 → stacked.fits                            │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ stack_dual_duo_m20 → stacked_Ha.fits,                   │
│                 │                                  │           │ stacked_OIII.fits, stacked_Sii.fits                     │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ background_m20_i3 → bk_stacked.fits                     │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ background_m20_i0 → bk_stacked_Ha.fits                  │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ background_m20_i1 → bk_stacked_OIII.fits                │
│ m20             │ 2025-09-23:light_SiiOiii_gain100 │ ✓ Success │ background_m20_i2 → bk_stacked_Sii.fits                 │
│ m101            │    2025-07-07:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m101_s25 → bkg_pp_light_s25_.seq         │
│ m101            │    2025-07-05:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m101_s26 → bkg_pp_light_s26_.seq         │
│ m101            │    2025-07-08:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m101_s24 → bkg_pp_light_s24_.seq         │
│ m101            │    2025-07-05:light_IRCUT_gain80 │ ⊘ Current │ stack_osc_m101 → stacked.fits                           │
│ m101            │    2025-07-05:light_IRCUT_gain80 │ ⊘ Current │ background_m101_i0 → bk_stacked.fits                    │
│ m106            │    2025-07-18:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m106_s28 → bkg_pp_light_s28_.seq         │
│ m106            │    2025-07-18:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_m106_s27 → bkg_pp_light_s27_.seq         │
│ m106            │    2025-07-18:light_IRCUT_gain80 │ ✓ Success │ stack_osc_m106 → stacked.fits                           │
│ m106            │    2025-07-18:light_IRCUT_gain80 │ ✓ Success │ background_m106_i0 → bk_stacked.fits                    │
│ ngc7023         │    2025-07-20:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_ngc7023_s47 → bkg_pp_light_s47_.seq      │
│ ngc7023         │    2025-07-20:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_ngc7023_s46 → bkg_pp_light_s46_.seq      │
│ ngc7023         │    2025-07-04:light_IRCUT_gain80 │ ✓ Success │ light_no_darks_ngc7023_s45 → bkg_pp_light_s45_.seq      │
│ ngc7023         │    2025-07-20:light_IRCUT_gain80 │ ⊘ Current │ stack_osc_ngc7023 → stacked.fits                        │
│ ngc7023         │    2025-07-20:light_IRCUT_gain80 │ ⊘ Current │ background_ngc7023_i0 → bk_stacked.fits                 │
│ ic1318b         │       2025-07-18:light_LP_gain80 │ ✓ Success │ light_no_darks_ic1318b_s19 → bkg_pp_light_s19_.seq      │
│ ic1318b         │       2025-07-18:light_LP_gain80 │ ✓ Success │ stack_osc_ic1318b → stacked.fits                        │
│ ic1318b         │       2025-07-18:light_LP_gain80 │ ✓ Success │ background_ic1318b_i0 → bk_stacked.fits                 │
│ m31             │    2025-08-25:light_None_gain100 │ ✓ Success │ light_vs_dark_m31_s2 → bkg_pp_light_s2_.seq             │
│ m31             │    2025-09-01:light_None_gain100 │ ✓ Success │ light_vs_dark_m31_s140 → bkg_pp_light_s140_.seq         │
│ m31             │    2025-09-01:light_None_gain100 │ ✗ Failed  │ Tool: 'siril -d                                         │
│                 │                                  │           │ /home/vscode/.cache/starbash/processing/m31 -s -'       │
│                 │                                  │           │ failed                                                  │
└─────────────────┴──────────────────────────────────┴───────────┴─────────────────────────────────────────────────────────┘
