# pyright: reportUndefinedVariable=false

"""Record per-frame Siril registration metrics in the image database.

Shared helper for the ``report_*`` TOML stages (see
``starbash-recipes/osc/report_registration.toml``). Each stage runs after one
of the ``stack_*.toml`` stages and points at that stack's representative
registered sequence via its ``seq_basename`` parameter:

- ``stack_osc`` -> ``r_in`` (basic OSC stacks ``r_in``, so ``r_in_.seq``
  carries the registration rows consumed by ``stack``)
- ``stack_single_duo`` / ``stack_dual_duo`` -> ``r_all_ha`` (duo Ha channel,
  ``merge ... all_ha`` + ``seqapplyreg all_ha`` writes ``r_all_ha_.seq``)

Mapping back to source images uses the provenance carried by the processing
task (`FileInfo.sequence_provenance` and `FileInfo.provenance`). Siril's merge
conversion report is not the right contract here: it describes the files
created by `merge`, while the report stage consumes the registered `r_*.seq`.
For the common merged case, the registered sequence retains the merged input
file number in each `I` record, so that number can be resolved against the
merged provenance. For a single-input duo stack, the helper processes the
per-session registered sequence directly.

Only selected sequence members update source rows. Failures warn and skip
without partial writes (``Database.update_images_metadata`` is atomic).
"""

import logging
from pathlib import Path
from typing import Any

from starbash.siril.import_registration import (
    RegistrationResult,
    parse_siril_seq,
)

# ('context' and 'logger' are normally injected by the starbash runtime)
context: dict[str, Any] = {}
logger: logging.Logger = None  # type: ignore


def _get_param(name: str, default: str) -> str:
    """Read a stage parameter (resolved into context["parameters"] by the runtime)."""
    params = context.get("parameters")
    value = getattr(params, name, None) if params is not None else None
    if value is None:
        return default
    return str(value)


def _log() -> logging.Logger:
    return logger if logger is not None else logging.getLogger(__name__)


def build_updates_from_provenance(
    results: list[RegistrationResult],
    provenance_by_name: dict[str, int],
    seq_basename: str,
) -> dict[int, dict[str, Any]]:
    """Map selected registration results to source IDs via merge provenance.

    ``merge_to()`` records ``{seq_basename}_{index:05d}.fits -> source ID``
    entries in ``FileInfo.provenance`` when it builds the merged directory.
    Pairing each parsed ``I`` record's `sequence_index` with that generated
    basename remains correct when `seqapplyreg` filters and compacts output.

    Raises:
        ValueError: On missing mapping or duplicate source IDs.
    """
    ordered_results = sorted(results, key=lambda r: r.sequence_index)
    updates: dict[int, dict[str, Any]] = {}
    for result in ordered_results:
        if not result.selected:
            continue
        source_id = None
        for ext in (".fits", ".fit"):
            candidate = f"{seq_basename}_{result.sequence_index:05d}{ext}"
            if candidate in provenance_by_name:
                source_id = provenance_by_name[candidate]
                break
        if source_id is None:
            raise ValueError(f"No database image for sequence index {result.sequence_index}")
        if source_id in updates:
            raise ValueError(f"Duplicate database image {source_id}")
        updates[source_id] = result.as_metadata()

    expected_count = sum(r.selected for r in ordered_results)
    assert len({r.sequence_index for r in ordered_results}) == len(ordered_results)
    assert len(updates) == expected_count
    if len(updates) != expected_count:
        raise ValueError(f"Mapped {len(updates)} selected images, expected {expected_count}")
    return updates


def _file_info_value(file_info: Any, name: str) -> Any:
    """Read a provenance field from a FileInfo or test dictionary."""
    value = getattr(file_info, name, None)
    if value is not None:
        return value
    return file_info.get(name) if isinstance(file_info, dict) else None


def _source_ids_for_report(
    seq_basename: str,
    inputs: dict[str, Any],
    sequence_provenance: dict[str, list[int]],
    provenance_by_name: dict[str, int] | None = None,
) -> list[int]:
    """Return ordered source IDs for the sequence selected by a report stage.

    The report task is planned before the stack action executes. It therefore
    must use the upstream named input (`ha` for duo stacks, the anonymous
    input for basic OSC), not a `FileInfo` mutation made by `merge_to()` while
    the stack action runs.
    """
    base = _strip_seq_suffix(seq_basename)
    upstream_base = base.removeprefix("r_")
    exact_keys = (
        f"{base}_.seq",
        f"{base}.seq",
        f"{upstream_base}_.seq",
        f"{upstream_base}.seq",
    )
    for key in exact_keys:
        ids = sequence_provenance.get(key)
        if ids:
            return list(dict.fromkeys(ids))

    selected_infos: list[Any] = []
    selected_infos.extend(inputs.values())

    source_ids: list[int] = []
    for file_info in selected_infos:
        provenance = _file_info_value(file_info, "sequence_provenance")
        if not isinstance(provenance, dict):
            continue
        for key, ids in provenance.items():
            if base in ("all_ha", "r_all_ha") and not Path(key).name.startswith(
                "r_Ha_bkg_pp_light"
            ):
                continue
            for source_id in ids:
                if source_id not in source_ids:
                    source_ids.append(source_id)
    if source_ids:
        return source_ids

    if provenance_by_name:
        indexed: list[tuple[int, int]] = []
        prefixes = (f"{base}_", f"{upstream_base}_")
        for name, source_id in provenance_by_name.items():
            basename = Path(name).name
            prefix = next((item for item in prefixes if basename.startswith(item)), None)
            if prefix is None:
                continue
            suffix = basename[len(prefix) :].split(".", 1)[0]
            if suffix.isdigit():
                indexed.append((int(suffix), source_id))
        return [source_id for _, source_id in sorted(indexed)]
    return []


def build_updates_from_inputs(
    results: list[RegistrationResult],
    source_ids_in_order: list[int],
) -> dict[int, dict[str, Any]]:
    """Map registered rows to source IDs using their preserved sequence index.

    Siril's output ``I`` record retains the input sequence's ``filenum`` even
    when ``seqapplyreg`` filters and compacts the output. Therefore
    ``sequence_index`` is an index into the merged/input sequence, not the
    position of the result row. This distinction prevents filtered frames from
    receiving another frame's metrics.
    """
    updates: dict[int, dict[str, Any]] = {}
    for result in sorted(results, key=lambda item: item.sequence_index):
        if not result.selected:
            continue
        source_position = result.sequence_index - 1
        if not 0 <= source_position < len(source_ids_in_order):
            raise ValueError(f"No database image for sequence index {result.sequence_index}")
        source_id = source_ids_in_order[source_position]
        if source_id in updates:
            raise ValueError(f"Duplicate database image {source_id}")
        updates[source_id] = result.as_metadata()

    expected_count = sum(result.selected for result in results)
    assert len({result.sequence_index for result in results}) == len(results)
    assert len(updates) == expected_count
    return updates


def _provenance_from_inputs(inputs: dict[str, Any]) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Union provenance and sequence-provenance across all input FileInfos."""
    provenance: dict[str, int] = {}
    sequence_provenance: dict[str, list[int]] = {}
    for file_info in inputs.values():
        prov = getattr(file_info, "provenance", None)
        if isinstance(prov, dict):
            provenance.update(prov)
        elif isinstance(file_info, dict) and isinstance(file_info.get("provenance"), dict):
            provenance.update(file_info["provenance"])
        seq_prov = getattr(file_info, "sequence_provenance", None)
        if isinstance(seq_prov, dict):
            sequence_provenance.update(seq_prov)
        elif isinstance(file_info, dict) and isinstance(file_info.get("sequence_provenance"), dict):
            sequence_provenance.update(file_info["sequence_provenance"])
    return provenance, sequence_provenance


def _strip_seq_suffix(name: str) -> str:
    if name.endswith("_.seq"):
        return name[: -len("_.seq")]
    if name.endswith(".seq"):
        return name[: -len(".seq")]
    return name


def _fallback_seq_basename(
    process_dir: Path, sequence_provenance: dict[str, list[int]], primary: str
) -> str | None:
    """Find a single usable sequence when the primary merged seq is absent.

    Covers the single-input no-merge case where ``make_stacked()`` registers
    the lone per-session sequence directly instead of merging to ``all_ha``.
    Returns None unless exactly one candidate exists on disk.
    """
    candidates: list[str] = []
    preferred_prefix = "r_Ha_bkg_pp_light" if primary.removeprefix("r_") == "all_ha" else None
    for seq_name in sequence_provenance:
        base = _strip_seq_suffix(Path(seq_name).name)
        if not base or base == primary:
            continue
        if preferred_prefix is not None and not base.startswith(preferred_prefix):
            continue
        for candidate in (base, f"r_{base}"):
            if (process_dir / f"{candidate}_.seq").is_file():
                candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0]
    return None


def update_from_seq(
    seq_basename: str,
    *,
    process_dir: str | Path | None = None,
    inputs: dict[str, Any] | None = None,
    updater: Any | None = None,
) -> int:
    """Parse ``{seq_basename}_.seq`` and update source image metadata.

    Returns the number of updated source rows (0 when skipped). Never raises:
    all failures are logged as warnings with no partial writes.
    """
    log = _log()
    try:
        workdir = Path(process_dir or context.get("process_dir", ""))
        if not str(workdir):
            raise ValueError("Missing process_dir for registration reporting")
        active_inputs: dict[str, Any] = inputs if inputs is not None else context.get("input", {})
        active_updater = updater if updater is not None else context.get("update_image_metadata")
        if active_updater is None:
            log.warning("Siril registration metadata updater is not configured; skipping")
            return 0

        _provenance, sequence_provenance = _provenance_from_inputs(active_inputs)
        if not _provenance and not sequence_provenance:
            raise ValueError("Missing registration source-name mapping")

        effective = seq_basename
        sequence_path = workdir / f"{effective}_.seq"
        if not sequence_path.is_file():
            fallback = _fallback_seq_basename(workdir, sequence_provenance, effective)
            if fallback is None:
                log.warning("Registration sequence %s not found; skipping", sequence_path)
                return 0
            log.info("Registration report: using single-input sequence %s", fallback)
            effective = fallback
            sequence_path = workdir / f"{effective}_.seq"

        log.info("Registration update: parsing %s", sequence_path)
        results = parse_siril_seq(sequence_path)
        log.info("Registration update: parsed %d results", len(results))

        # Use the ordered source IDs from the upstream stage. A registered
        # sequence may contain fewer rows than its input after seqapplyreg
        # filtering, so the result's retained sequence_index must select the
        # source ID rather than result-row position.
        ordered_ids = _source_ids_for_report(
            effective, active_inputs, sequence_provenance, _provenance
        )
        updates = build_updates_from_inputs(results, list(ordered_ids))

        expected_count = sum(r.selected for r in results)
        assert len(updates) == expected_count
        updated_count = active_updater(updates)
        assert updated_count == expected_count
        log.info("Registration update: updated %d source image records", updated_count)
        return updated_count
    except Exception as exc:
        _log().warning("Unable to update Siril registration metadata: %s", exc)
        return 0


def update_from_params() -> int:
    """Entry point for TOML stages: read ``seq_basename`` from stage parameters."""
    return update_from_seq(_get_param("seq_basename", "r_in"))
