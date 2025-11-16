# doit

## Plan
idea for next version:
fixme - instead we should just have a depends="seqextract_HaOIII", which in turn
depends="calibrate_light_from_bias" | "calibrate_light_from_dark".  then starbash can build a dependency graph of stages
to run based on what is needed?
resolve | dependencies by priority - prefer higher pri stage (calibrate_light_from_dark)
if that stage .is_allowed() && .has_inputs()

fundamentally: on the input side we have a list of sessions.
on the output side we have some FITS files our pipeline promises to make
we want to have full dependency tree from those outputs back to the inputs
plus added dependencies on the recipe stages and masters which might be used to make
those outputs.

btw: masters are handled in the same tree of dependencies.  a master depends on
its raw inputs
possibly useful? https://pydoit.org/dependencies.html and
https://pydoit.org/cmd-run.html#using-the-api

the stack would depend on seqextract_HaOIII (which would require appropriate filters to be considered)
so to process a set of sessions:
stages would be selected based on what stages are permitted by auto.require?

any way to link these stages based on the output files also?

## Notes

When doing processing we have as inputs:
* a set of **possible** recipes
* a set of **possible** raw darks, flats and biases
* a set of selected light sessions

Based on the targets in the selected light sessions we can build a set of required outputs:
* a set of output targetdirs with a glob showing mininum set of files for success?

FIXME: explain culling and how it fits into the workflow.

The single boxes are one once, the stacked boxes (like in 'calibrate_lights') are run once per session.

Tasks are only run if they are needed by a downstream task.  i.e. most times raws_to_master_flat will not need to run at all.  Because the graph will capture the input file to output file dependencies.

Each of the tasks are implemented by a single Tool (currently Siril, Graxpert or python).  As an optimization before execution any adjacent Siril tasks will be merged into a **single** Siril invocation.

Initially use the current master-gen code, but plan for possibly using dependencies for that as well.

## doit concepts

Create a custom task loader to create (programmatically) my tree of tasks: https://pydoit.org/extending.html#example-pre-defined-task

A Task dict has:
* name
* help
* actions
* (optional) file_dep: list[str]
* (optional) targets: list[str]
Note: if file_dep and targets are equal between two different tasks (as a str cmp), doit will automatically realize there is a dependency there

Possibly the main entrypoint to start dependency processing would be (after creating and culling tasks) would be something like "doit graxpert_noise_elim:{targetdir}/no-noise.fits. https://pydoit.org/tasks.html#sub-task-selection?
Stages could force doit to be invoked by having a line something like:
default_outputs = [ "{taskdir}/nonoise.fits" ]
which would cause the corresponding created task to be referenced by our doit code?

Or instead/in-addition doit supports wildcard resolution so "doit graxpert_noise_elim:{taskdir}/*.fits" would match against any fits file the corrsponding task lists as its "targets"


Make a custom ToolAction that uses our tool concept.

tasks are passed source, sinks and targets.  These are the key links for dependencies?
https://pydoit.org/tutorial-1.html

task can return task-groups (with yield).  Use this for stuff like multisession image calibration? https://pydoit.org/tutorial-1.html#package-imports

Use "uptodate" to create extra dependencies on the recipes that were used to make particular tasks.  https://pydoit.org/dependencies.html



## typical graph

A typical (after culling) set of tasks is something like this (dual duo band OSC filter shown):

```mermaid
%% to experiment with mermaid GUI go here:
%% https://www.mermaidchart.com/play?utm_source=mermaid_live_editor&utm_medium=toggle#pako:eNpVjLEOgjAURX_lpZMO_QEGEynKQqIDW-3wUottlL6mNCGG8u-CLHrXc86dmKa7YQXrXjRqizFBW908LDtKYaMbUo-DAs4PuTYJevLmnaHc1QSDpRCcf-w3v1wlEFOzagaSdf45b0h8-4s3GSrZYEgU1C9pR8pwku5ql_t_YqNZqrPssOiQa4wgMCo2fwBnHTpc

flowchart
    session_flat@{ shape: disk } --> raws_to_master_flat
    session_dark@{ shape: disk } --> raws_to_master_dark
    session_light@{ shape: disk } --> |selected_light_sessions| calibrate_lights
    raws_to_master_dark --> |autoselected_master_dark.fits|raws_to_master_flat
    raws_to_master_flat --> |autoselected_master_flat.fits| calibrate_lights
    calibrate_lights@{ shape: procs} --> pp_lights
    pp_lights@{ shape: procs} --> seqextract_hao3
    seqextract_hao3@{ shape: procs} --> register

    %% The following are done 1 to small-N times depending on ha/oiii/single/multi-channel-mono-camera
    %% called 'make_stacked' in current code

    register --> register_pass2
    register_pass2 --> drizzle
    drizzle --> stack
    stack --> perhaps_mirror
    perhaps_mirror --> multichannel_pixelmath

    %% the following is done zero to small-N as needed to combine results
    %% called make_renormalize in current code

    multichannel_pixelmath --> update_fits_metadata
    update_fits_metadata --> save_o3
    update_fits_metadata --> save_ha
    update_fits_metadata --> save_s2

    save_o3 --> |"{targdir}/o3.fits"|pixmath_combine
    save_ha --> |"{targdir}/ha.fits"|pixmath_combine
    save_s2 --> |"{targdir}/s2.fits"|pixmath_combine

    pixmath_combine --> |"{targdir}/combined.fits"| graxpert_bkg_removal
    graxpert_bkg_removal --> |"{targdir}/no_bkg.fits"|graxpert_noise_elim
    graxpert_noise_elim --> g1["{targetdir}/no_noise.fits"]@{ shape: das}
```

