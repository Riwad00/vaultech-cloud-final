"""Pure diagnosis function — no FastAPI dependency.

Takes a piece dict (cumulative timestamps) and returns the response dict
following the §1.4 schema. Applies the §1.3 delay-detection rules.
"""

from __future__ import annotations

from typing import Any

from .causes import CAUSES, SEGMENT_ORDER


def _partial(a: float | None, b: float | None) -> float | None:
    """Return (a - b) unless either operand is None/NaN."""
    if a is None or b is None:
        return None
    try:
        if a != a or b != b:  # NaN check
            return None
    except TypeError:
        return None
    return round(a - b, 4)


def _absolute(a: float | None) -> float | None:
    """Return a (furnace→2nd has no prior timestamp) unless None/NaN."""
    if a is None:
        return None
    try:
        if a != a:
            return None
    except TypeError:
        return None
    return round(a, 4)


def _compute_partials(piece: dict[str, Any]) -> dict[str, float | None]:
    """Compute the 5 partial times from cumulative timestamps (§1.5).

    If either operand is NULL/missing, the partial is NULL — a single missing
    cumulative value can nullify two adjacent partials.
    """
    lt_2nd = piece.get("lifetime_2nd_strike_s")
    lt_3rd = piece.get("lifetime_3rd_strike_s")
    lt_4th = piece.get("lifetime_4th_strike_s")
    lt_aux = piece.get("lifetime_auxiliary_press_s")
    lt_bath = piece.get("lifetime_bath_s")

    return {
        "furnace_to_2nd_strike": _absolute(lt_2nd),
        "2nd_to_3rd_strike": _partial(lt_3rd, lt_2nd),
        "3rd_to_4th_strike": _partial(lt_4th, lt_3rd),
        "4th_strike_to_aux_press": _partial(lt_aux, lt_4th),
        "aux_press_to_bath": _partial(lt_bath, lt_aux),
    }


def _classify(actual: float | None, reference: float) -> tuple[float | None, bool | None]:
    """Apply the §1.3 rule. Returns (deviation_s, penalized)."""
    if actual is None:
        return None, None
    deviation = round(actual - reference, 4)
    if deviation > 5.0:
        return deviation, None
    if deviation > 1.0:
        return deviation, True
    return deviation, False


def diagnose(piece: dict[str, Any], reference_times: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Diagnose one piece according to §1.3–§1.4.

    Raises:
        ValueError: if die_matrix is unknown (caller converts to HTTP 400).
    """
    piece_id = piece.get("piece_id")
    die_matrix = piece.get("die_matrix")

    if die_matrix is None:
        raise ValueError("missing die_matrix")

    matrix_key = str(int(die_matrix))
    if matrix_key not in reference_times:
        raise ValueError(f"unknown die_matrix {die_matrix}")

    refs = reference_times[matrix_key]
    partials = _compute_partials(piece)

    segments: list[dict[str, Any]] = []
    any_penalized = False
    causes: list[str] = []

    for seg in SEGMENT_ORDER:
        actual = partials[seg]
        reference = refs[seg]
        deviation, penalized = _classify(actual, reference)

        segments.append({
            "segment": seg,
            "actual_s": None if actual is None else round(actual, 1),
            "reference_s": round(reference, 1),
            "deviation_s": None if deviation is None else round(deviation, 1),
            "penalized": penalized,
        })

        if penalized is True:
            any_penalized = True
            causes.extend(CAUSES[seg])

    return {
        "piece_id": piece_id,
        "die_matrix": int(die_matrix),
        "delay": any_penalized,
        "segments": segments,
        "probable_causes": causes,
    }
