"""Tests for the pure diagnose() function.

Covers the 4 matrices × 6 scenarios grid required by the exam (24 unit tests),
plus the parametrized golden test against validation_pieces.csv /
validation_expected.json.

All tests call diagnose() directly — no HTTP server, no FastAPI dependency.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.diagnose import diagnose

API_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_TIMES_PATH = API_ROOT / "reference_times.json"
VALIDATION_CSV = API_ROOT / "validation_pieces.csv"
VALIDATION_JSON = API_ROOT / "validation_expected.json"

with open(REFERENCE_TIMES_PATH) as f:
    REFS: dict[str, dict[str, float]] = json.load(f)

MATRICES = [4974, 5052, 5090, 5091]
SEGMENTS = [
    "furnace_to_2nd_strike",
    "2nd_to_3rd_strike",
    "3rd_to_4th_strike",
    "4th_strike_to_aux_press",
    "aux_press_to_bath",
]
DELAY = 2.5  # inside the (1.0, 5.0] penalty band


def _cumulatives(partials: dict[str, float]) -> dict[str, float]:
    """Turn 5 partial times into the 5 cumulative timestamps."""
    a = partials["furnace_to_2nd_strike"]
    b = a + partials["2nd_to_3rd_strike"]
    c = b + partials["3rd_to_4th_strike"]
    d = c + partials["4th_strike_to_aux_press"]
    e = d + partials["aux_press_to_bath"]
    return {
        "lifetime_2nd_strike_s": round(a, 2),
        "lifetime_3rd_strike_s": round(b, 2),
        "lifetime_4th_strike_s": round(c, 2),
        "lifetime_auxiliary_press_s": round(d, 2),
        "lifetime_bath_s": round(e, 2),
    }


def _piece(matrix: int, partials: dict[str, float], piece_id: str = "TEST") -> dict:
    return {"piece_id": piece_id, "die_matrix": matrix, **_cumulatives(partials)}


def _all_ok_partials(matrix: int) -> dict[str, float]:
    return dict(REFS[str(matrix)])


def _penalize(matrix: int, segment: str) -> dict[str, float]:
    partials = _all_ok_partials(matrix)
    partials[segment] = round(partials[segment] + DELAY, 2)
    return partials


# ── 4 × 6 = 24 unit tests ─────────────────────────────────────────────────────

@pytest.mark.parametrize("matrix", MATRICES)
def test_all_ok(matrix):
    """Scenario 1: All segments match reference → delay=False, no penalized segments."""
    piece = _piece(matrix, _all_ok_partials(matrix))
    result = diagnose(piece, REFS)
    assert result["delay"] is False
    assert result["probable_causes"] == []
    for seg in result["segments"]:
        assert seg["penalized"] is False


@pytest.mark.parametrize("matrix", MATRICES)
def test_furnace_to_2nd_penalized(matrix):
    piece = _piece(matrix, _penalize(matrix, "furnace_to_2nd_strike"))
    result = diagnose(piece, REFS)
    assert result["delay"] is True
    penalized = [s["segment"] for s in result["segments"] if s["penalized"] is True]
    assert penalized == ["furnace_to_2nd_strike"]
    assert "Billet pick" in result["probable_causes"]


@pytest.mark.parametrize("matrix", MATRICES)
def test_2nd_to_3rd_penalized(matrix):
    piece = _piece(matrix, _penalize(matrix, "2nd_to_3rd_strike"))
    result = diagnose(piece, REFS)
    assert result["delay"] is True
    penalized = [s["segment"] for s in result["segments"] if s["penalized"] is True]
    assert penalized == ["2nd_to_3rd_strike"]
    assert "press/PLC handshake" in result["probable_causes"]


@pytest.mark.parametrize("matrix", MATRICES)
def test_3rd_to_4th_penalized(matrix):
    piece = _piece(matrix, _penalize(matrix, "3rd_to_4th_strike"))
    result = diagnose(piece, REFS)
    assert result["delay"] is True
    penalized = [s["segment"] for s in result["segments"] if s["penalized"] is True]
    assert penalized == ["3rd_to_4th_strike"]
    assert "conservative trajectory" in result["probable_causes"]


@pytest.mark.parametrize("matrix", MATRICES)
def test_4th_to_aux_press_penalized(matrix):
    piece = _piece(matrix, _penalize(matrix, "4th_strike_to_aux_press"))
    result = diagnose(piece, REFS)
    assert result["delay"] is True
    penalized = [s["segment"] for s in result["segments"] if s["penalized"] is True]
    assert penalized == ["4th_strike_to_aux_press"]
    assert "queue at Auxiliary Press entry" in result["probable_causes"]


@pytest.mark.parametrize("matrix", MATRICES)
def test_aux_press_to_bath_penalized(matrix):
    piece = _piece(matrix, _penalize(matrix, "aux_press_to_bath"))
    result = diagnose(piece, REFS)
    assert result["delay"] is True
    penalized = [s["segment"] for s in result["segments"] if s["penalized"] is True]
    assert penalized == ["aux_press_to_bath"]
    assert "bath deposit" in result["probable_causes"]


# ── Edge-case tests for the §1.3 rule boundaries ──────────────────────────────

def test_deviation_above_5s_is_null():
    """deviation > 5.0 → penalized=null (sensor anomaly, not a delay)."""
    partials = _all_ok_partials(5090)
    partials["furnace_to_2nd_strike"] += 6.0  # big anomaly
    piece = _piece(5090, partials)
    result = diagnose(piece, REFS)
    first = result["segments"][0]
    assert first["penalized"] is None
    assert result["delay"] is False  # anomaly doesn't count as delay


def test_missing_cumulative_nullifies_two_partials():
    """A single NULL cumulative nullifies both adjacent partials."""
    partials = _all_ok_partials(5052)
    piece = _piece(5052, partials)
    piece["lifetime_3rd_strike_s"] = None  # NULL
    result = diagnose(piece, REFS)
    seg_by_name = {s["segment"]: s for s in result["segments"]}
    assert seg_by_name["2nd_to_3rd_strike"]["penalized"] is None
    assert seg_by_name["3rd_to_4th_strike"]["penalized"] is None
    assert seg_by_name["furnace_to_2nd_strike"]["penalized"] is False


def test_unknown_matrix_raises_value_error():
    piece = {"piece_id": "X", "die_matrix": 9999,
             "lifetime_2nd_strike_s": 18.0, "lifetime_3rd_strike_s": 25.0,
             "lifetime_4th_strike_s": 38.0, "lifetime_auxiliary_press_s": 55.0,
             "lifetime_bath_s": 57.0}
    with pytest.raises(ValueError, match="unknown die_matrix"):
        diagnose(piece, REFS)


# ── Golden test: 10 validation pieces must match validation_expected.json ─────

def _load_validation_rows() -> list[dict]:
    with open(VALIDATION_CSV) as f:
        reader = csv.DictReader(f)
        return list(reader)


def _csv_row_to_piece(row: dict) -> dict:
    def maybe_float(v: str) -> float | None:
        return None if v == "" else float(v)
    return {
        "piece_id": row["piece_id"],
        "die_matrix": int(row["die_matrix"]),
        "lifetime_2nd_strike_s": maybe_float(row["lifetime_2nd_strike_s"]),
        "lifetime_3rd_strike_s": maybe_float(row["lifetime_3rd_strike_s"]),
        "lifetime_4th_strike_s": maybe_float(row["lifetime_4th_strike_s"]),
        "lifetime_auxiliary_press_s": maybe_float(row["lifetime_auxiliary_press_s"]),
        "lifetime_bath_s": maybe_float(row["lifetime_bath_s"]),
    }


@pytest.fixture(scope="module")
def expected_map() -> dict[str, dict]:
    with open(VALIDATION_JSON) as f:
        expected = json.load(f)
    return {p["piece_id"]: p for p in expected}


@pytest.mark.parametrize("row", _load_validation_rows(), ids=lambda r: r["piece_id"])
def test_golden_validation_piece(row, expected_map):
    """Golden test: each validation piece's diagnose() output matches expected JSON."""
    piece = _csv_row_to_piece(row)
    actual = diagnose(piece, REFS)
    expected = expected_map[piece["piece_id"]]
    # Round actual to 1 decimal for comparison (same as expected values)
    assert actual == expected
