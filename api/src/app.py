"""FastAPI application for the forging line delay-diagnostics API.

Endpoints:
    POST /diagnose       — receives one piece, returns the diagnosis (§1.4)
    GET  /openapi.json   — served automatically by FastAPI
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .diagnose import diagnose

# Resolve reference_times.json relative to the package root
API_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_TIMES_PATH = API_ROOT / "reference_times.json"

app = FastAPI(
    title="Forging Line Delay Diagnostics API",
    description="Receives cumulative timestamps for one piece and returns per-segment diagnosis.",
    version="1.0.0",
)

# Load reference_times.json ONCE at startup (§2.1, checklist item, rubric §3)
with open(REFERENCE_TIMES_PATH) as f:
    REFERENCE_TIMES: dict[str, dict[str, float]] = json.load(f)


class PieceRequest(BaseModel):
    """Input schema — 7 fields, 5 cumulative lifetimes may be null."""

    piece_id: str
    die_matrix: int
    lifetime_2nd_strike_s: float | None = None
    lifetime_3rd_strike_s: float | None = None
    lifetime_4th_strike_s: float | None = None
    lifetime_auxiliary_press_s: float | None = None
    lifetime_bath_s: float | None = None


@app.exception_handler(HTTPException)
async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    # Keep the plain {"error": "..."} body shape from §2.1 regardless of status code
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})


@app.post("/diagnose")
def diagnose_endpoint(piece: PieceRequest) -> dict[str, Any]:
    """Diagnose one piece. Route handler delegates to the pure diagnose() function."""
    try:
        return diagnose(piece.model_dump(), REFERENCE_TIMES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
