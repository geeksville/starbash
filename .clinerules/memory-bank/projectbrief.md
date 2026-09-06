# Project Brief

## Project Name
**Starbash** — a tool for automating, standardizing, and sharing astrophotography workflows.

## Repository
https://github.com/geeksville/starbash

## One-line Summary
A CLI-first ("seestar-like" auto-processing) tool that indexes FITS image metadata, organizes imaging sessions, and runs shareable processing "recipes" (Siril/GraXpert/Starnet/BlurXTerminator/Python) to calibrate and stack images per target.

## Core Requirements & Goals

1. **Automatic** — just a few keystrokes (`sb process auto`) to auto-process an entire repo of raw images, with sensible, customizable defaults. Automatic master bias/dark/flat generation and automatic preprocessing, stacking, and background elimination.

2. **Shareable recipes** — image preprocessing flows are described as small, atomic, human-readable TOML "recipes" (analogous to `npm`/`make`/`git` for astrophotography). Recipes can come from multiple repos (local or remote HTTP/GitHub), and orgs/users can host their own.

3. **Multi-session by default** — workflows stack from multiple nights and still select/auto-generate the correct flats, darks, and biases per session (matched by instrument, camera, gain, filter, temperature, dimensions, and date proximity).

4. **Full FITS/session-aware history** — select targets by name, date range, instrument, filter, image type; query a SQLite-backed index of all FITS metadata.

5. **Attribution & reproducibility** — track instrument, raw images, processed-by, recipe source/version for the final image. Each target's processing choices are persisted in a `starbash.toml` that can be edited and re-run.

6. **Tool agnostic** — Starbash is *not* a new image-processing tool; it orchestrates existing tools. Currently supported: Siril, GraXpert, Starnet2, rc-astro (BlurXTerminator/NoiseXTerminator), and Python (RestrictedPython sandbox). PixInsight planned.

7. **Optional publishing** — generate a GitHub Pages-compatible report website and publish processed targets to a public `starbash-public` repo (`sb publish github`).

## Scope (what it is / is not)

- **Is NOT** a new image processing tool, nor a set of opaque scripts. It is a repeatable/sharable/semi-automated workflow manager focused on the relationships between tools, images, and sessions.
- Starbash understands FITS metadata and how to invoke tools based on it; the actual image transformations are defined by recipes.

## Current Status
Alpha (version 0.3.1, tagged 2026-08-31). OSC (color camera) workflows are the primary supported path; mono-camera workflows are planned but not yet available.

## License
GPL v3. Copyright 2025 Kevin Hester (kevinh@geeksville.com).