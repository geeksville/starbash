# Product Context

## Why this project exists
Astrophotography produces large numbers of raw FITS frames across multiple nights, instruments, filters, and software (NINA, Asiair, Seestar, Dwarf3). Turning those into a finished image today means a maze of opaque, buried scripts and manual steps: picking calibration frames (biases/darks/flats) that actually match the lights, registering and stacking, background extraction, star removal, and documenting what was done. This is slow, error-prone, and unrepeatable.

Starbash exists to make that workflow automatic, reproducible, and shareable — the way `npm`/`make`/`git` made software builds automatic, reproducible, and shareable.

## Problems it solves

1. **Automatic calibration matching** — automatically generates/selects the correct master bias, dark, and flat for each light session, matched by instrument/camera/gain/filter/temperature/dimensions and date proximity.
2. **Multi-session stacking** — stacks a target across many nights by default, while still using the correct per-session calibration.
3. **Opaque scripts** — replaces long, buried shell/python scripts with small, atomic, human-readable TOML "recipes" that have explicit inputs, outputs, parameters, and inter-stage dependencies.
4. **Reproducibility & attribution** — persists every processing choice in a per-target `starbash.toml`; records instrument, raw images, processed-by, and recipe source/version.
5. **Session/FITS-aware querying** — a SQLite index of all FITS metadata lets users select by target, date, instrument, filter, and image type without rescanning.
6. **Sharing workflows** — recipe repos can be local or remote (HTTP/GitHub), so users and orgs can publish and consume each other's processing flows.

## How it should work

1. **Setup**: `sb user setup` (or first launch) prompts for name/email/analytics and input/master/processed repo locations.
2. **Index**: `sb repo add <path>` scans a raw-image tree, reads FITS headers, and populates the SQLite database (images + aggregated sessions).
3. **Select**: `sb select target m31`, `sb select date after 2025-09-01`, etc., filter the working set (persisted in user config).
4. **Process**: `sb process auto` picks a recipe per target, generates masters, then runs stage jobs through doit to calibrate, register, stack, background-eliminate, and star-remove, writing final FITS + JPEG thumbnails + a `starbash.toml` report.
5. **Customize/re-run**: edit the generated `starbash.toml` (e.g., pick different masters, exclude stages) and reprocess.
6. **Publish** (optional): `sb publish github` generates a GitHub Pages site describing the processed targets.

## User experience goals

- **Seestar-like ease**: "just type `sb process auto` and it will probably do okay for your first attempt." Sensible, customizable defaults.
- **Fast to operate** (not necessarily fast to compute): few keystrokes to process an entire repo; rich, live progress (spinners, progress bars, streaming tool logs).
- **Human-readable & editable**: recipes and per-target configs are TOML, readable and editable by hand.
- **Safe**: never modifies input repos; processed outputs go to a separate "processed" repo. Metadata is anonymized (SITELONG/SITELAT blacklisted) to avoid leaking location PII.
- **Friendly**: clear warnings when external tools are missing; graceful handling of bad FITS files; helpful links to installation docs.