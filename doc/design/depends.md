* currently when the user changes an override for a parameter "sb process auto" doesnt trigger a rebuild of the corresponding stage.
* change this (by creating a doit dependecy?) so that we notice the change and properly rebuild

ie if a user changes private/processed/ngc6888/starbash.toml
```
[[stages]]
name = "light_no_darks" # Calibrate OSC lights that have no dark frames available
[[stages.overrides]]
name = "options" # Light frame calibration options for OSC cameras
value = "-somenew-opt"
```

to be able to detect this we must keep a snapshot of the values used in the previous run.  can you keep it in the doit db somehow?  is this a standard concept in doit?