# Broadband workflows (bb1)

Make `broadband` (non-narrowband) targets flow through the same downstream
recipes as narrowband targets (`starnet` → `veralux` → `merge_stars` →
`thumbnail`).

## Problem

Narrowband targets run `starbash-recipes/palette/hoo.toml` and
`starbash-recipes/palette/sho.toml`, which gate on the input session's filter:

```toml
[[stages.inputs.requires]]
kind = "metadata"
name = "filter"
value = ["HaOiii", "SiiOiii"]
```

This selects runs that have **either** (OR) of those two filter types.
Broadband targets (e.g. `sh2-126`, filter `Tri` → normalized alias `None`) match
neither, so they produce no `palette.*` output. `starbash-recipes/common/starnet.toml`
runs `after = "palette.*"`, so with no palette output it (and everything
downstream of it) is skipped.

## Changes

1. **Add an optional `invert` clause to any `requires` node** in
   `src/starbash/filtering.py::_apply_filter`. It negates the boolean match:

   ```toml
   [[stages.inputs.requires]]
   kind = "metadata"
   name = "filter"
   value = ["HaOiii", "SiiOiii"]
   invert = true
   ```

   This selects runs whose filter is **neither** HaOiii nor SiiOiii. It applies to
   the boolean-match kinds (`metadata`, `camera`, `unprocessed`, `filename`); it is
   not meaningful for `min_count`.

2. **Add `starbash-recipes/palette/broadband.toml`** — a simple load/save that
   writes `broadband.fits` to the processed directory (mirrors the structure of
   `hoo.toml`/`sho.toml` but does no channel combining):

   ```toml
   [[stages]]
   name = "palette_broadband"
   tool.name = "siril"
   script = '''
       load "{input[0].full_paths[0]}"
       save "{output.full_paths[0]}"
       '''

   [[stages.inputs]]
   kind = "job"
   after = "noise_exterminator"

   [[stages.inputs.requires]]
   kind = "metadata"
   name = "filter"
   value = ["HaOiii", "SiiOiii"]
   invert = true

   [[stages.inputs.requires]]
   kind = "min_count"
   value = 1

   [[stages.outputs]]
   kind = "processed"
   name = ["broadband.fits"]
   ```

   Downstream naming then works for free: `starless_broadband.fits` /
   `starmask_broadband.fits` (starnet) → `hms_starless_broadband.fits` (veralux)
   → `merged_broadband.fits` (merge_stars) → thumbnails.

3. **Register the recipe** in `starbash-recipes/starbash.toml` (`[[repo-ref]]`
   `dir = "palette/broadband.toml"`), listed **after** the narrowband palettes so
   it is the fallback.

4. **Update docs**: `doc/toml/guide.md`, `AGENTS.md`, and
   `.github/copilot-instructions.md` to document the `invert` clause and the
   broadband palette pass-through recipe.

5. **Add tests**:
   - `tests/unit/test_filtering.py` — `metadata`/`invert` keeps non-matching
     filters.
   - `tests/unit/test_tool.py` — `palette_broadband` is a siril pass-through with
     `after = "noise_exterminator"`, an inverted metadata filter, a `min_count`,
     and output `broadband.fits`; the default manifest references the recipe.

## Decisions

- `invert` is generic (inverts any boolean `requires` node), matching "any requires
  node" — not metadata-only.
- The broadband palette is non-multiplexed with a single `input[0]` (broadband
  produces one stacked file), consistent with the "simple" description.
- `palette/broadband.toml` is listed last among palettes (fallback position).

## Validation

The currently selected target is `sh2-126`. Run `sb --debug process auto` and
confirm from the logs that `palette_broadband` → `starnet` → `veralux` →
`merge_stars` → `thumbnail` are now scheduled (and `palette_sho`/`palette_hoo`
are not).

