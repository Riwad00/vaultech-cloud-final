# Forging Line Delay Diagnostics API

FastAPI service that receives cumulative timestamps for a single forged piece and
returns a per-segment delay diagnosis with probable root causes.

## Run locally

```bash
cd api
uv sync
uv run uvicorn src.app:app --host 0.0.0.0 --port 80
```

Then test:

```bash
curl -X POST http://localhost:80/diagnose \
  -H "Content-Type: application/json" \
  -d '{"piece_id":"P001","die_matrix":4974,"lifetime_2nd_strike_s":17.3,"lifetime_3rd_strike_s":23.5,"lifetime_4th_strike_s":36.5,"lifetime_auxiliary_press_s":52.3,"lifetime_bath_s":54.0}'
```

## Tests

```bash
cd api
uv run pytest -v
```
