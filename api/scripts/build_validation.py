"""Generate validation_pieces.csv and validation_expected.json programmatically.

The CSV contains 10 pieces that cover every meaningful path of the diagnose
function (§1.4 coverage map). The expected JSON is produced by running the
same diagnose() used by the API — no hand-written values.

Run:
    uv run python scripts/build_validation.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

from src.diagnose import diagnose  # noqa: E402

REFERENCE_TIMES_PATH = API_ROOT / "reference_times.json"
CSV_PATH = API_ROOT / "validation_pieces.csv"
JSON_PATH = API_ROOT / "validation_expected.json"

with open(REFERENCE_TIMES_PATH) as f:
    REFS: dict[str, dict[str, float]] = json.load(f)


def cumulatives_from_partials(partials: dict[str, float]) -> dict[str, float]:
    """Convert segment partials to the 5 cumulative lifetime fields."""
    lt_2nd = partials["furnace_to_2nd_strike"]
    lt_3rd = lt_2nd + partials["2nd_to_3rd_strike"]
    lt_4th = lt_3rd + partials["3rd_to_4th_strike"]
    lt_aux = lt_4th + partials["4th_strike_to_aux_press"]
    lt_bath = lt_aux + partials["aux_press_to_bath"]
    return {
        "lifetime_2nd_strike_s": round(lt_2nd, 2),
        "lifetime_3rd_strike_s": round(lt_3rd, 2),
        "lifetime_4th_strike_s": round(lt_4th, 2),
        "lifetime_auxiliary_press_s": round(lt_aux, 2),
        "lifetime_bath_s": round(lt_bath, 2),
    }


def all_ok(matrix: str) -> dict[str, float]:
    """Partial times equal to reference — no penalty anywhere."""
    return dict(REFS[matrix])


def bump(matrix: str, segment: str, delta: float) -> dict[str, float]:
    """Reference partials with one segment increased by delta."""
    partials = dict(REFS[matrix])
    partials[segment] = round(partials[segment] + delta, 2)
    return partials


# P001–P004: all-OK on each matrix (deviation = 0 everywhere → penalized: false)
# P005–P009: single-segment delay (+2.5s → deviation 2.5s, inside 1.0 < d ≤ 5.0 → true)
# P010: multi-segment delay on 5090 PLUS a NULL cumulative timestamp
DELAY = 2.5  # within the (1.0, 5.0] penalty band

pieces_raw: list[dict[str, object]] = [
    {"piece_id": "P001", "die_matrix": "4974", **cumulatives_from_partials(all_ok("4974"))},
    {"piece_id": "P002", "die_matrix": "5052", **cumulatives_from_partials(all_ok("5052"))},
    {"piece_id": "P003", "die_matrix": "5090", **cumulatives_from_partials(all_ok("5090"))},
    {"piece_id": "P004", "die_matrix": "5091", **cumulatives_from_partials(all_ok("5091"))},
    {"piece_id": "P005", "die_matrix": "4974",
     **cumulatives_from_partials(bump("4974", "furnace_to_2nd_strike", DELAY))},
    {"piece_id": "P006", "die_matrix": "5052",
     **cumulatives_from_partials(bump("5052", "2nd_to_3rd_strike", DELAY))},
    {"piece_id": "P007", "die_matrix": "5090",
     **cumulatives_from_partials(bump("5090", "3rd_to_4th_strike", DELAY))},
    {"piece_id": "P008", "die_matrix": "5091",
     **cumulatives_from_partials(bump("5091", "4th_strike_to_aux_press", DELAY))},
    {"piece_id": "P009", "die_matrix": "4974",
     **cumulatives_from_partials(bump("4974", "aux_press_to_bath", DELAY))},
]

# P010: multi-segment delay AND a NULL cumulative.
# Strategy:
#   - furnace_to_2nd_strike: delay (use actual lifetime_2nd_strike_s = ref + DELAY)
#   - lifetime_3rd_strike_s: NULL (this nullifies 2nd_to_3rd AND 3rd_to_4th partials)
#   - lifetime_4th_strike_s: still provided but 3rd_to_4th will be NULL because 3rd is NULL
#   - 4th_strike_to_aux_press: delay (+DELAY above reference)
#   - aux_press_to_bath: OK
matrix_p010 = "5090"
ref_p010 = REFS[matrix_p010]
lt_2nd_p010 = round(ref_p010["furnace_to_2nd_strike"] + DELAY, 2)
# 4th strike value doesn't matter for 3rd_to_4th (NULL propagates) — pick a sensible one
lt_4th_p010 = round(lt_2nd_p010 + ref_p010["2nd_to_3rd_strike"] + ref_p010["3rd_to_4th_strike"], 2)
lt_aux_p010 = round(lt_4th_p010 + ref_p010["4th_strike_to_aux_press"] + DELAY, 2)
lt_bath_p010 = round(lt_aux_p010 + ref_p010["aux_press_to_bath"], 2)

pieces_raw.append({
    "piece_id": "P010",
    "die_matrix": matrix_p010,
    "lifetime_2nd_strike_s": lt_2nd_p010,
    "lifetime_3rd_strike_s": None,          # NULL — nullifies two partials
    "lifetime_4th_strike_s": lt_4th_p010,
    "lifetime_auxiliary_press_s": lt_aux_p010,
    "lifetime_bath_s": lt_bath_p010,
})


# ── Write CSV ─────────────────────────────────────────────────────────────────
fieldnames = [
    "piece_id", "die_matrix",
    "lifetime_2nd_strike_s", "lifetime_3rd_strike_s", "lifetime_4th_strike_s",
    "lifetime_auxiliary_press_s", "lifetime_bath_s",
]
with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in pieces_raw:
        writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in fieldnames})


# ── Generate expected JSON by running diagnose() on each piece ────────────────
expected: list[dict] = []
for row in pieces_raw:
    piece_dict = dict(row)
    piece_dict["die_matrix"] = int(row["die_matrix"])
    expected.append(diagnose(piece_dict, REFS))

with open(JSON_PATH, "w") as f:
    json.dump(expected, f, indent=2)

print(f"Wrote {CSV_PATH}")
print(f"Wrote {JSON_PATH} ({len(expected)} pieces)")
print()
print("Coverage:")
for p in expected:
    penalized = [s["segment"] for s in p["segments"] if s["penalized"] is True]
    null_segs = [s["segment"] for s in p["segments"] if s["penalized"] is None]
    print(f"  {p['piece_id']:5s} matrix={p['die_matrix']} delay={p['delay']!s:5s} "
          f"penalized={penalized} null={null_segs}")
