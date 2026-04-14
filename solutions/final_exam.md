# Final Exam — Theoretical Questions

## 3.1 API Design

### Question 1

The request schema for `POST /diagnose` has exactly seven fields:

1. `piece_id` — string identifier for the piece
2. `die_matrix` — integer (one of 4974, 5052, 5090, 5091) that selects which reference profile to compare against
3. `lifetime_2nd_strike_s` — cumulative seconds from furnace exit to the 2nd strike
4. `lifetime_3rd_strike_s` — cumulative seconds from furnace exit to the 3rd strike
5. `lifetime_4th_strike_s` — cumulative seconds from furnace exit to the 4th strike (drill)
6. `lifetime_auxiliary_press_s` — cumulative seconds from furnace exit to the auxiliary press
7. `lifetime_bath_s` — cumulative seconds from furnace exit to the quench bath

**Why cumulative input and not pre-computed partials.** The raw PLC emits cumulative times — that is how the sensors naturally capture each piece's progress (time zero is the furnace exit, each stage records its elapsed time). Any client that feeds this API (the Streamlit dashboard, a Kafka consumer, an SCADA bridge, a notebook) has the cumulative values in hand and would otherwise have to subtract them itself. Pushing that derivation into the API centralises the formulas in one place (`src/diagnose.py::_compute_partials`) so clients cannot disagree about what "partial time" means — the API owns the contract. It also matches the gold dataset's cumulative lifetime columns one-to-one, so the same format works for batch scoring.

**Why this set is the minimum necessary.** The response in §1.4 requires a `reference_s`, `deviation_s` and `penalized` value per segment. There are five segments, and each segment's formula in §1.5 references exactly two cumulative timestamps (except the first, which uses only `lifetime_2nd_strike_s`). The five lifetime fields together are the minimal set that lets us compute every partial. `die_matrix` is required because the reference table is keyed by matrix — you literally cannot build the response without it. `piece_id` echoes into the response so callers can correlate the request and the answer. Dropping any of the seven fields would either produce a NULL segment that could have been computed, or make the diagnosis impossible.

### Question 2

`reference_times.json` is read once at module import time inside `src/app.py`:

```python
with open(REFERENCE_TIMES_PATH) as f:
    REFERENCE_TIMES: dict[str, dict[str, float]] = json.load(f)
```

The route handler then passes this already-loaded dict into `diagnose(piece, REFERENCE_TIMES)`. This is the right approach for a containerised deployment for three reasons.

**Performance.** The file is small (~600 bytes) but opening a file per request still requires a syscall, a filesystem seek, a decode and a JSON parse. At a few thousand requests per second that cost compounds and adds unpredictable tail latency. Loading once amortises the cost over the lifetime of the container, so every `POST /diagnose` does only the work that differs between requests (run the rules, build the response).

**Immutability of the artefact.** The container image is built with `reference_times.json` baked in (see the `Dockerfile` `COPY reference_times.json ./` line). The file cannot change while the container is running, so there is nothing to reload. If new medians are computed, we produce a new image, push it to ECR, and roll the Fargate task — the versioned artefact, not a live file, is the source of truth. Reading the file every request would invite the wrong mental model (that it is "live data") and encourage someone to mount a volume or hot-swap it, which defeats the reproducibility of immutable containers.

**12-factor configuration principle.** Configuration that is specific to a build (reference medians, cause tables, model version) lives inside the image. Configuration that is specific to an environment (endpoint URLs, region) lives in environment variables. Reading at startup lets us apply the first half of that split cleanly: the image IS the config for anything that doesn't change per deployment.

## 3.2 Containerization And Deployment

### Question 1

My `Dockerfile` has seven key instructions. Going through them in order:

```dockerfile
FROM python:3.13-slim
```

The base image is the official `python:3.13-slim` variant on Debian. `3.13` matches the `requires-python = ">=3.13"` pin in `api/pyproject.toml` so I get the same interpreter I tested locally. The `-slim` variant ships only the essentials (no compilers, no man pages, no extra locales) which keeps the final image small (~150 MB vs ~1 GB for the full `python:3.13`). That matters for ECR storage and, more importantly, for ECS task startup — Fargate pulls the image on every cold start, so a smaller image means faster `PROVISIONING → RUNNING` transitions.

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
```

This copies the `uv` binary from Astral's official image into my image in one go. I use `uv` as the package manager throughout the project and this saves the ~10 s of installing it via pip or curl.

```dockerfile
WORKDIR /app
COPY pyproject.toml README.md ./
RUN uv sync --no-dev --no-install-project
```

Dependency files are copied *before* the source tree, and I run `uv sync` without installing the project itself. This is deliberate — Docker caches layers keyed on the content hash of their inputs. My `pyproject.toml` changes rarely; my source changes every edit. By installing dependencies in a dedicated layer whose input is just `pyproject.toml`, iterative rebuilds after a source edit reuse the expensive dependency-install layer from cache. That single decision turns a 40-second rebuild into a 2-second one.

```dockerfile
COPY src/ src/
COPY reference_times.json ./
RUN uv sync --no-dev
```

Now that dependencies are cached, I bring in the code and the reference file, then run `uv sync` again to install the project itself as a package. Keeping `reference_times.json` in the image (not mounted at runtime) is what makes the container reproducible — the same image will always diagnose pieces against the same medians.

```dockerfile
EXPOSE 80
CMD ["uv", "run", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "80"]
```

`EXPOSE 80` is documentation (it tells the image reader and tooling what port the container listens on; it doesn't actually publish the port). `CMD` uses exec form (JSON array) so Uvicorn receives POSIX signals directly — when ECS sends `SIGTERM` for a task stop, Uvicorn shuts down gracefully instead of being killed after the 30 s grace period. `--host 0.0.0.0` is mandatory for a container (binding to `127.0.0.1` would only accept traffic from inside the container). Port 80 matches what the security group allows, so no port translation is needed anywhere downstream.

### Question 2

Two alternatives to ECS Fargate:

**AWS Lambda (with API Gateway or a Function URL).** Lambda is serverless function-as-a-service — you give it a container image or a zip of your code and AWS runs a new execution environment on demand. *Advantage:* true scale-to-zero — I pay nothing when no pieces are being diagnosed, which is ideal for an intermittent workload. The cold start on a Python container is only ~1 s for an app this size. *Disadvantage:* Lambda's execution model is request-scoped. Each invocation may run a fresh container or reuse a warm one at AWS's discretion, so I cannot rely on in-process state. In practice that means I could not cache `reference_times.json` the way I do today across requests with 100% certainty; more importantly, a FastAPI app is designed as a long-running server with a startup lifecycle, whereas Lambda wants handler functions. I would either need to use Mangum (a FastAPI-to-Lambda adapter) or rewrite the handler. For a long-lived, consistently-queried API, Fargate's steady container model fits better.

**Amazon EC2 with an Auto Scaling Group behind an Application Load Balancer.** This is the "traditional" model — a fleet of VMs running Docker (or systemd + Uvicorn) behind an ALB. *Advantage:* maximum control. I can pick instance types, use Graviton for cost savings, install any OS-level package, SSH in to debug, and attach block storage if I need it. *Disadvantage:* operational overhead. I would be responsible for OS patching, AMI builds, Docker daemon upgrades, health checks, rolling deployments, and ASG configuration. For an API this small, all of that is undifferentiated heavy lifting. Fargate abstracts the instance layer away — I declare a task definition and get a container running with no host to maintain.

Fargate was the right choice here: it runs the container I built with minimal operational burden, integrates with ECR for image pulls, and scales without my code changing.

## 3.3 Testing And Extensibility

### Question 1

The exam asks for `diagnose()` to be tested as a pure function for four reasons:

**Speed.** My test suite has 37 tests and runs in ~30 ms. An HTTP-based equivalent would need to start Uvicorn, wait for the port to be listening, send a request, parse the response, and tear the server down for each test — at least a second per test, probably more with connection setup. Fast tests are run-often tests; slow tests get skipped.

**Determinism.** A pure function takes an input dict and returns an output dict. There is no network, no file descriptor shortage, no port collision, no TCP timeout. Test flakiness is almost always caused by the infrastructure around the code under test, not the code itself. Isolating the logic means failures are real failures, not "a port was busy in CI."

**Enforcement of the pure-function boundary.** By testing `diagnose()` directly, the exam makes it architecturally impossible for business rules to creep into the FastAPI route handler. My `src/app.py` has exactly one line of real logic inside `diagnose_endpoint()`:

```python
return diagnose(piece.model_dump(), REFERENCE_TIMES)
```

If I had written the rules there, the golden test could not reach them without an HTTP call. Testing the pure function forces the right factoring, which also makes it trivial to reuse `diagnose()` elsewhere (a batch scorer, a CLI tool, an async worker) without dragging FastAPI along.

**Framework independence.** FastAPI, Uvicorn, Pydantic — any of these could be swapped (Starlette, Hypercorn, msgspec) and none of my tests would need to change. The diagnosis contract belongs to the business, not to the web framework.

### Question 2

Adding die matrix `6001` requires changes in exactly three places — there is no retraining, no model artefact, no deployment pipeline beyond a rebuild because my API is a rules engine, not an ML inference service.

**1 — Data artefact: `api/reference_times.json`.** I compute the five reference medians for matrix 6001 from production data (the same median-per-matrix calculation I already do in §1.2, run against a sample of 6001 pieces in the gold dataset). I add a new key:

```json
"6001": {
  "furnace_to_2nd_strike": 17.8,
  "2nd_to_3rd_strike":      6.6,
  "3rd_to_4th_strike":     13.5,
  "4th_strike_to_aux_press": 16.8,
  "aux_press_to_bath":       1.7
}
```

No schema change — just a new entry in an existing dict. The API picks it up on startup.

**2 — Code: nothing.** My `diagnose()` in `src/diagnose.py` does not hardcode matrices. It does `matrix_key = str(int(die_matrix))` and looks it up in the reference-times dict:

```python
if matrix_key not in reference_times:
    raise ValueError(f"unknown die_matrix {die_matrix}")
```

As soon as 6001 is a valid key in the dict, calls with `die_matrix: 6001` stop returning HTTP 400 and start returning a diagnosis. The cause table in `src/causes.py` is keyed by *segment*, not by matrix, so it already covers 6001 (the five segments exist independently of which matrix made the piece).

**3 — Tests: add 6 scenarios to `api/tests/test_diagnose.py`.** The parametrized tests are keyed on a `MATRICES` list:

```python
MATRICES = [4974, 5052, 5090, 5091]
```

I change this to `[4974, 5052, 5090, 5091, 6001]` and the six parametrised tests (`test_all_ok`, `test_furnace_to_2nd_penalized`, ...) automatically expand to 30 unit tests (5 matrices × 6 scenarios). I also add at least one new validation piece to `validation_pieces.csv` that targets 6001, regenerate `validation_expected.json` with `uv run python scripts/build_validation.py`, and the golden test picks it up automatically.

**Deployment.** Rebuild the Docker image (`docker buildx build --platform linux/amd64 -t diagnose-api:latest --load .`), push to ECR (`docker push <account>.dkr.ecr.eu-west-1.amazonaws.com/diagnose-api:latest`), force a new ECS deployment (`aws ecs update-service --cluster diagnose-api-cluster --service diagnose-api-service --force-new-deployment --region eu-west-1`). Because ECS pulls the image on task start, within ~60 s the task is serving the new configuration. Zero downtime if I run with desired-count ≥ 2 and a rolling deployment; a short restart if desired-count is 1.

What I explicitly do **not** need to change: no ML retraining (there is no model), no SageMaker endpoint, no IAM roles (the task role already has `ecsTaskExecutionRole` for the image pull and no other AWS call is needed), no VPC or security group, no task-definition CPU/memory (the workload is identical). The API was designed so adding a matrix is a data change, not a code change — that is the whole point of keeping the reference values in JSON rather than hardcoding them.
