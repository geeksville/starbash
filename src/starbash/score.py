import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import tomlkit
from tomlkit.items import Table

from starbash.database import (
    Database,
    SessionRow,
    metadata_to_camera_id,
    metadata_to_instrument_id,
)
from starbash.toml import AsTomlMixin

__all__ = [
    "ScoredCandidate",
    "score_candidates",
]


@dataclass
class ScoredCandidate(AsTomlMixin):
    """Our helper structure for scoring candidate sessions will return lists of these."""

    candidate: dict[str, Any]  # the scored candidate
    score: float  # a score - higher is better.  higher scores will be at the head of the list
    reason: str  # short explanation of why this score (comma-joined, for humans)
    #: The individual reason fragments the rankers appended, kept as a list so the
    #: explanation can be written to TOML as *data* rather than a comment.
    reasons: list[str] = field(default_factory=list)
    #: Structured scoring evidence (gain/temp/time/instrument/camera/... deltas and
    #: match flags).  Keys are exactly as written to ``sessions.toml`` so a reader
    #: never has to parse the human ``reason`` string.
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def get_comment(self) -> str:
        """Generate a comment string for this candidate."""
        return f"{round(self.score)} {self.reason}"

    def __str__(self) -> str:
        """As a formatted toml node with documentation comment"""
        s: str = self.candidate["path"]  # Must be defined by now, FIXME, use abspath instead?
        return s

    def to_toml_table(self) -> Table:
        """Serialize to a ``[[…masters.<type>.candidates]]`` table.

        The structured :attr:`details` keys are written alongside the score so a
        reader can rank and explain a candidate without re-running the scorer, and
        the human summary is written as a ``reasons`` **array** (never a comment).
        """
        table = tomlkit.table()
        table["path"] = str(self.candidate.get("path", ""))
        table["score"] = round(self.score, 1)
        for key, value in self.details.items():
            table[key] = value
        table["reasons"] = list(self.reasons) or ([self.reason] if self.reason else [])
        return table


def score_candidates(
    candidates: list[dict[str, Any]], ref_session: SessionRow
) -> list[ScoredCandidate]:
    """Given a list of images or sessions, try to rank that list by desirability.

    Return a list of possible images/sessions which would be acceptable.  The more desirable
    matches are first in the list.  Possibly in the future I might have a 'score' and reason
    given for each ranking.

    The following critera MUST match to be acceptable:
    * matches requested imagetyp.
    * same telescope as reference session

    Quality is determined by (most important first):
    * GAIN setting is as close as possible to the reference session (very high penalty for mismatch)
    * same filter as reference session (in the case want_type==FLAT only)
    * smaller DATE-OBS delta to the reference session (within same week beats 5°C temp difference)
    * temperature of CCD-TEMP is closer to the reference session

    Eventually the code will check the following for 'nice to have' (but not now):
    * TBD

            Implementation notes:
            - This uses a list of inner "ranker" functions that each compute a score contribution
                and may append to a shared 'reasons' list from the outer closure. This makes it easy
                to add new ranking dimensions by appending another function to the list.

    """
    from starbash.aliases import get_aliases

    metadata: dict = ref_session.get("metadata", {})

    # Now score and sort the candidates
    scored_candidates: list[ScoredCandidate] = []

    for candidate in candidates:
        score = 0.0
        reasons: list[str] = []
        #: Structured scoring evidence; each ranker records what it measured.
        details: dict[str, Any] = {}

        # Get candidate image metadata to access CCD-TEMP and DATE-OBS
        try:
            candidate_image = candidate  # metadata is already in the root of this object

            # Define rankers that close over candidate_image, ref_*, reasons and details
            def rank_gain(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Score by GAIN difference: prefer exact match, penalize mismatch."""
                ref_gain = metadata.get(Database.GAIN_KEY, None)
                if ref_gain is None:
                    return 0.0
                candidate_gain = candidate_image.get(Database.GAIN_KEY)
                if candidate_gain is None:
                    return 0.0
                try:
                    gain_diff = abs(float(ref_gain) - float(candidate_gain))
                    # Massive bonus for exact match, linear heavy penalty otherwise
                    gain_score = 30000 - 1000 * gain_diff
                    details["gain_match"] = gain_diff == 0
                    details["gain_delta"] = float(gain_diff)
                    if gain_diff > 0:
                        reasons.append(f"gain Δ={gain_diff:.0f}")
                    else:
                        reasons.append("gain match")
                    return float(gain_score)
                except (ValueError, TypeError):
                    return 0.0

            def rank_temp(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Score by CCD-TEMP difference: prefer closer temperatures."""
                ref_temp = metadata.get("CCD-TEMP", None)
                if ref_temp is None:
                    return 0.0
                candidate_temp = candidate_image.get("CCD-TEMP")
                if candidate_temp is None:
                    return 0.0
                try:
                    temp_diff = abs(float(ref_temp) - float(candidate_temp))
                    # Exponential decay: closer temps get better scores
                    temp_score = 500 * (2.718 ** (-temp_diff / 5))
                    details["temp_delta_c"] = float(temp_diff)
                    if temp_diff >= 0.2:  # don't report tiny differences
                        reasons.append(f"temp Δ={temp_diff:.1f}°C")
                    return float(temp_score)
                except (ValueError, TypeError):
                    return 0.0

            def rank_time(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Score by time difference: prefer older or slightly newer candidates."""
                ref_date_str = metadata.get(Database.DATE_OBS_KEY)
                candidate_date_str = candidate_image.get(Database.DATE_OBS_KEY)
                if not (ref_date_str and candidate_date_str):
                    return 0.0
                try:
                    ref_date = datetime.fromisoformat(ref_date_str)  # type: ignore[arg-type]
                    candidate_date = datetime.fromisoformat(candidate_date_str)
                    time_delta = (candidate_date - ref_date).total_seconds()
                    days_diff = time_delta / 86400
                    in_future = time_delta > 0 and days_diff > 2.0
                    details["time_delta_days"] = float(days_diff)
                    details["in_future"] = bool(in_future)
                    # Prefer candidates OLDER or less than 2 days newer
                    if not in_future:
                        # 7-day half-life, weighted higher than temp
                        time_score = 1000 * (2.718 ** (-abs(time_delta) / (7 * 86400)))
                        reasons.append(f"time Δ={days_diff:.1f}d")
                    else:
                        # Penalize candidates >2 days newer by 10x
                        time_score = 100 * (2.718 ** (-abs(time_delta) / (7 * 86400)))
                        reasons.append(f"time Δ={days_diff:.1f}d (in future!)")
                    return float(time_score)
                except (ValueError, TypeError):
                    logging.warning("Malformed date - ignoring entry")
                    return 0.0

            def rank_instrument(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Penalize instrument mismatch between reference and candidate."""
                ref_instrument = metadata_to_instrument_id(metadata)
                candidate_instrument = metadata_to_instrument_id(candidate_image)
                details["instrument_match"] = ref_instrument == candidate_instrument
                if ref_instrument != candidate_instrument:
                    reasons.append("instrument mismatch")
                    return -200000.0
                return 0.0

            def rank_camera(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Penalize camera mismatch between reference and candidate."""
                ref_camera = metadata_to_camera_id(metadata)
                candidate_camera = metadata_to_camera_id(candidate_image)
                details["camera_match"] = ref_camera == candidate_camera
                if ref_camera != candidate_camera:
                    reasons.append("camera mismatch")
                    return -300000.0
                return 0.0

            def rank_camera_dimensions(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Penalize if camera dimensions do not match (NAXIS, NAXIS1, NAXIS2)."""
                dimension_keys = ["NAXIS", "NAXIS1", "NAXIS2"]
                details["dimensions_match"] = True
                for key in dimension_keys:
                    ref_value = metadata.get(key)
                    candidate_value = candidate_image.get(key)
                    if ref_value != candidate_value:
                        details["dimensions_match"] = False
                        reasons.append(f"{key} mismatch")
                        return float("-inf")
                return 0.0

            def rank_flat_filter(
                reasons: list[str] = reasons,
                details: dict[str, Any] = details,
                candidate_image: dict[str, Any] = candidate_image,
            ) -> float:
                """Heavily penalize FLAT frames whose FILTER metadata does not match the reference.

                Only applies if the candidate imagetyp is FLAT. Missing filter values are treated as None
                and do not cause a penalty (neutral)."""
                # Default to "None" (as the filter lookups below do) so a missing
                # imagetyp is neutral rather than crashing normalize().
                imagetyp = get_aliases().normalize(
                    candidate_image.get(Database.IMAGETYP_KEY, "None"),
                    lenient=True,
                )
                if imagetyp and imagetyp == "flat":
                    ref_filter = get_aliases().normalize(
                        metadata.get(Database.FILTER_KEY, "None"), lenient=True
                    )
                    candidate_filter = get_aliases().normalize(
                        candidate_image.get(Database.FILTER_KEY, "None"), lenient=True
                    )
                    details["filter_match"] = ref_filter == candidate_filter
                    if ref_filter != candidate_filter:
                        reasons.append("filter mismatch")
                        return -100000.0
                    else:
                        reasons.append("filter match")
                return 0.0

            rankers = [
                rank_gain,
                rank_temp,
                rank_time,
                rank_instrument,
                rank_camera,
                rank_camera_dimensions,
                rank_flat_filter,
            ]

            # Apply all rankers and check for unusable candidates
            for r in rankers:
                contribution = r()
                score += contribution
                # If any ranker returns -inf, this candidate is unusable
                if contribution == float("-inf"):
                    break

            # Only keep usable candidates
            if score != float("-inf"):
                reason = ", ".join(reasons) if reasons else "no scoring factors"
                scored_candidates.append(
                    ScoredCandidate(
                        candidate=candidate,
                        score=score,
                        reason=reason,
                        reasons=list(reasons),
                        details=dict(details),
                    )
                )

        except (AssertionError, KeyError) as e:
            # If we can't get the session image, log and skip this candidate
            logging.warning(f"Could not score candidate session {candidate.get('id')}: {e}")
            continue

    # Sort by score (highest first)
    scored_candidates.sort(key=lambda x: x.score, reverse=True)

    return scored_candidates
