# Output handling: downstream stages consume the wrong output

## Symptoms

Adding a second output block to `starbash-recipes/osc/stack_single_duo.toml` causes the GraXpert background stage to run on `.seq` files:

```text
OSError: Could not find a backend to open
.../r_all_r_OIII_bkg_pp_light_.seq
```

The `.seq` files are intermediate Siril job artifacts. They should not be passed to GraXpert, which expects image files such as FITS files in this workflow.

## Reproduction

`stack_single_duo.toml` declares both final processed outputs and intermediate job outputs:

```toml
[[stages.outputs]]
kind = "processed"
name = [
    "stacked_Ha.fits",
    "stacked_OIII.fits"
]

[[stages.outputs]]
kind = "job"
name = [
    "r_all_r_Ha_bkg_pp_light_.seq",
    "r_all_r_OIII_bkg_pp_light_.seq"
]
```

The background recipe currently asks for the output of a prior `stack_*` stage:

```toml
[[stages.inputs]]
kind = "job"
after = "stack_.*"
multiplex = true
```

## Root cause

`Processing._resolve_output_files()` in `src/starbash/processing.py` resolves each output block but stores each result in the same context key:

```python
self.context["output"] = r
```

Therefore, output blocks are effectively **last-output-wins** for the runtime context. When the `job` output block is last, the prior task's saved `context["output"]` contains only the `.seq` files.

`Processing._import_from_prior_stages()` then imports `task_context["output"]` without selecting an output kind. The input declaration's `kind = "job"` does not currently mean “select the prior output block whose kind is `job`”; it only selects the job-input resolver. There is no `processed` input kind or output-kind selector today.

The existing `filename` requirement filter can reject the `.seq` files:

```toml
[[stages.inputs.requires]]
kind = "filename"
value = "\\.fits$"
```

but this is only a guard. It cannot recover the processed FITS outputs after they have been overwritten in `context["output"]`.

## Secondary impact

The output overwrite can also affect the producing stage itself. `src/starbash/recipes/osc.py` uses:

```python
context["output"].base
```

for the destination directory of the stacked/renormalized files. If a `job` output is processed last, `context["output"].base` points at the processing/job directory instead of the processed target directory. Thus output declaration order may alter both:

- which files downstream stages consume; and
- where the producing recipe writes its final files.

## Temporary workaround

Until output selection is made explicit, declare the `processed` output block last. This preserves the current last-output-wins behavior for this workflow:

```toml
[[stages.outputs]]
kind = "job"
name = [
    "r_all_r_Ha_bkg_pp_light_.seq",
    "r_all_r_OIII_bkg_pp_light_.seq"
]

[[stages.outputs]]
kind = "processed"
name = [
    "stacked_Ha.fits",
    "stacked_OIII.fits"
]
```

This is fragile and should not be treated as the long-term design. If the `.seq` files are not needed as declared task targets, removing the extra `job` output block is simpler.

## Recommended long-term design

Preserve all output `FileInfo` objects by output kind in the task context, for example:

```python
context["outputs"] = {
    "processed": processed_file_info,
    "job": job_file_info,
}
```

Retain `context["output"]` as a backwards-compatible alias for the stage's primary/final output, but do not use it as the only representation of outputs.

Add an explicit selector to downstream input definitions, for example:

```toml
[[stages.inputs]]
kind = "job"
after = "stack_.*"
output_kind = "processed"
multiplex = true
```

Then update `Processing._import_from_prior_stages()` to select the requested output kind from `task_context["outputs"]`, rather than assuming the last output block is the desired one.

The exact spelling (`output_kind` versus `output-kind`) should follow the repository's TOML naming convention. The semantic requirement is that the downstream input explicitly chooses which output kind it consumes.

The implementation should also make the producing stage's primary output stable, so adding another output block cannot redirect code such as `osc.py` to a different directory.

## Why this is preferable to a filename filter

A filename filter is useful as a defensive constraint, especially for tools that accept only certain file types. It should not be the main way to select between output channels, because:

- filenames do not reliably identify the semantic output kind;
- a valid processed output might use a different extension or naming convention;
- filtering cannot select an output that was discarded from the prior task context; and
- the same output-kind collision could affect other recipes and tools.

The clean model is: output declarations publish multiple named/kinded products, and downstream inputs explicitly select the product they need. Filename filtering can remain as an additional safety check.

## Suggested future tests

Add processing tests covering:

1. A stage with both `processed` and `job` output blocks retains both `FileInfo` objects.
2. Output declaration order does not change the primary processed output directory.
3. A downstream input with `output_kind = "processed"` receives only processed rows.
4. A downstream input with `output_kind = "job"` receives only job rows.
5. A filename requirement still filters the selected output rows.
6. A missing or unknown output kind produces a clear configuration error.
7. The background recipe does not create GraXpert tasks for `.seq` outputs.

## Relevant code

- `src/starbash/processing.py`
  - `Processing._resolve_output_files()`
  - `Processing._stage_output_files()`
  - `Processing._import_from_prior_stages()`
  - `Processing._resolve_input_files()`
- `src/starbash/recipes/osc.py`
  - `make_stacked()`
  - `make_renormalize()`
- `src/starbash/filtering.py`
  - `_apply_filter()` supports the existing `filename` requirement
- `starbash-recipes/osc/stack_single_duo.toml`
- `starbash-recipes/graxpert/background.toml`
