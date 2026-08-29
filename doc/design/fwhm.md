building on the work in doc/design/report.md now add support for:
* after stacking images use the siril registration results to add 5 new bits of metadata in our db of images input images - so that later tools can use that data
* add siril seq parsing per fixme in src/starbash/siril/import_registration.py
* when making this plan search for fixme-ai in src/starbash/recipes/osc.py for important tips
* use asserts to doublecheck that you correctly found and updated the correct number of existing input image db records
* for now we only want to add this new feature to src/starbash/recipes/osc.py based stages. others like starbash-recipes/osc/stack_osc.toml will come later
* now that fwhm is in the db change the reporting so it uses the real values (if not present do not include in the [[about]] report)
* add test cases as appropriate

